import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from subprocess import CompletedProcess
from threading import Event
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient

TEMP = tempfile.TemporaryDirectory()
os.environ["STUDY_DATA"] = TEMP.name
from backend import main as app
from backend.demo import SAMPLE, ROAD
from backend.physics import calculate, grade
from backend.models import Motion, Roadmap


class Study(unittest.TestCase):
    def test_provider_routing(self):
        settings={"provider":"codex","codex_model":"test-model"}
        with patch.object(app.providers,"codex_result",return_value=ROAD) as cli:
            self.assertEqual(app.ai.structured(Roadmap,"plan",{},settings=settings),ROAD)
            self.assertIs(cli.call_args.args[0],Roadmap)
            self.assertEqual(cli.call_args.kwargs["model"],"test-model")
        steps=[dict(action="calculator",arguments_json='{"expression":"2+3"}',sources=[],text=""),
               dict(action="answer",arguments_json="{}",sources=[],text="5")]
        with patch.object(app.providers,"codex_result",side_effect=steps) as cli:
            result=app.ai.chat({},[],"2+3",False,settings=settings)
            self.assertEqual(result["traces"][0]["output"],{"result":5})
            self.assertTrue(all(call.kwargs["model"]=="test-model" for call in cli.call_args_list))
        with patch.dict(os.environ,{"OPENAI_API_KEY":"env-test-key"}):
            self.assertEqual(app.providers.api_key({}),"env-test-key")
            self.assertNotIn("OPENAI_API_KEY",app.providers.cli_environment())

    def test_tools(self):
        self.assertAlmostEqual(calculate("0.5*9.81*2**2"), 19.62)
        self.assertTrue(grade(SAMPLE["quiz"][0],"1962 cm"))
        self.assertFalse(grade(SAMPLE["quiz"][0],"19.62 s"))
        self.assertRaises(ValueError, calculate, "open('file')")
        self.assertRaises(ValueError, calculate, "4**1000")
        data = app.motion(Motion())
        self.assertAlmostEqual(data["points"][120]["s"],19.62)

    def test_lesson_retries_invalid_codex_output(self):
        road = app.commit(Roadmap.model_validate(ROAD))
        rid, tid = road["id"], road["chapters"][0]["topics"][0]["id"]
        lesson = deepcopy(SAMPLE)
        lesson["quiz"][0]["answer"] = "-6 kg·m/s"
        broken = deepcopy(lesson)
        broken["quiz"][0]["answer"] = "p = -6 kg·m/s"

        def response(doc):
            event = {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(doc)}}
            return CompletedProcess([], 0, json.dumps(event), "")

        with patch.object(app, "ai_settings", return_value={"provider": "codex"}), \
             patch.object(app.providers, "cli_status", return_value="ready"), \
             patch.object(app.providers.subprocess, "run", side_effect=[response(broken), response(lesson)]) as run, \
             self.assertLogs(app.providers.log, level="WARNING") as logs:
            doc = app.generate(rid, tid)
            self.assertEqual(app.generate(rid, tid), doc)
        self.assertEqual(run.call_count, 2)
        self.assertIn("quiz.0 (value_error)", run.call_args.kwargs["input"])
        self.assertIn("quiz.0 (value_error)", logs.output[0])
        self.assertTrue(grade(doc["quiz"][0], "-6 kg⋅m/s"))

    def test_course_and_conversations(self):
        with patch.object(app.ai,"structured",return_value=ROAD):
            draft=app.draft(app.Draft(subject="Vật lý",level="Mới học",goal="Cơ học",schedule="1 giờ"))
        road=app.commit(Roadmap.model_validate(draft))
        rid,tid=road["id"],road["chapters"][0]["topics"][0]["id"]
        frozen=(app.DATA/rid/"roadmap.json").read_bytes()
        with patch.object(app.ai,"structured",return_value=SAMPLE) as generate:
            doc=app.generate(rid,tid)
            self.assertEqual(doc,app.generate(rid,tid))
            generate.assert_called_once()
        note=app.note(rid,tid,app.Anchor(block="intro",start=0,end=3,quote="Nếu",version=doc["version"]))
        with patch.object(app.ai,"chat",return_value=dict(role="assistant",text="Đã hiểu",sources=[])) as chat:
            app.send(rid,tid,note["id"],app.Message(text="Câu hỏi riêng"))
            app.send(rid,tid,"main",app.Message(text="Câu hỏi chính"))
            self.assertEqual(chat.call_args.args[1],[])
            self.assertNotIn("highlight",chat.call_args.args[0])
        self.assertEqual(app.read_chat(rid,tid,note["id"])[0]["text"],"Câu hỏi riêng")
        app.quiz(rid,tid,app.Attempt(question=0,answer="1962 cm"))
        self.assertEqual((app.DATA/rid/"roadmap.json").read_bytes(),frozen)
        self.assertTrue(app.read(rid,tid)["progress"]["0"][0]["correct"])


    def test_question_threads_keep_separate_histories(self):
        road = app.commit(Roadmap.model_validate(ROAD))
        rid, tid = road["id"], road["chapters"][0]["topics"][0]["id"]
        path = f"/api/chat/{rid}/{tid}"
        first, second, empty = ("question-" + uuid4().hex for _ in range(3))
        app.put(f"lesson:{rid}:{tid}", dict(SAMPLE, version=uuid4().hex))
        with TestClient(app.app) as client, patch.object(app.ai, "chat", return_value={"role": "assistant", "text": "Reply"}) as chat:
            self.assertEqual(client.get(f"{path}/{empty}").json(), [])
            for branch, text in [("main", "Earlier question"), (first, "First question"), (second, "Second question"), (first, "Follow-up")]:
                self.assertEqual(client.post(f"{path}/{branch}", json={"text": text}).status_code, 200)
            self.assertEqual([msg["text"] for msg in chat.call_args.args[1]], ["First question", "Reply"])
            self.assertEqual(client.get(path).json(), [
                {"id": first, "question": "First question"},
                {"id": second, "question": "Second question"},
                {"id": "main", "question": "Earlier question"},
            ])
            self.assertEqual([msg["text"] for msg in client.get(f"{path}/{first}").json()],
                             ["First question", "Reply", "Follow-up", "Reply"])
            self.assertEqual(len(client.get(f"{path}/{second}").json()), 2)


class TutorContext(unittest.TestCase):
    rid, tid = "physics", "free-fall"
    reply = {"role": "assistant", "text": "19.62 m"}

    def setUp(self):
        self.doc = app.lesson_for(self.rid, self.tid)
        quote = self.doc["intro"][:8]
        highlight = app.note(self.rid, self.tid, app.Anchor(
            version=self.doc["version"], block="intro", start=0, end=len(quote), quote=quote,
            snapshot={"k": uuid4().int % 1_000_000}))
        self.branch = highlight["id"]
        self.key = f"thread:{self.rid}:{self.tid}:{self.branch}"
        self.path = f"/api/chat/{self.rid}/{self.tid}/{self.branch}"
        self.env = patch.dict(os.environ, {"STUDY_BOUNDED_CONTEXT": "0"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def send(self, text, request_id=None):
        return app.send(self.rid, self.tid, self.branch, app.Message(text=text, request_id=request_id))

    def test_duplicate_and_parallel_branches(self):
        started, resume = Event(), Event()
        request_id = uuid4()
        legacy = [{"role": "user", "text": "Legacy question"}, self.reply]
        app.put(self.key, legacy)

        def provider(*args, **kwargs):
            if args[2] == "Original":
                started.set()
                if not resume.wait(10):
                    raise TimeoutError("Test did not release provider")
            return self.reply

        with patch.object(app.ai, "chat", side_effect=provider) as calls, ThreadPoolExecutor() as pool:
            process = pool.submit(self.send, "Original", request_id)
            try:
                self.assertTrue(started.wait(10))
                with TestClient(app.app) as client:
                    for body in ({"text": "Original", "request_id": str(request_id)}, {"text": "Competing"}):
                        response = client.post(self.path, json=body, headers={"X-Study-Language": "en"})
                        self.assertEqual(response.status_code, 409)
                        self.assertEqual(response.headers["Retry-After"], "1")
                    self.assertEqual(client.get(self.path).json(), legacy)
                    another = client.post(f"/api/chat/{self.rid}/{self.tid}/main", json={"text": "Independent"})
                    self.assertEqual(another.status_code, 200)
            finally:
                resume.set()
            committed = process.result(timeout=10)
            self.assertEqual(committed, legacy + [{"role": "user", "text": "Original"}, self.reply])
            self.assertEqual(self.send("Original", request_id), committed)
            with self.assertRaises(HTTPException) as reused:
                self.send("Different question", request_id)
            self.assertEqual(reused.exception.status_code, 409)
            self.assertEqual(calls.call_count, 2)
        with app.db() as conn:
            sequence = conn.execute("SELECT committed_revision FROM tutor_requests WHERE request_id=?",
                                    (str(request_id),)).fetchone()[0]
        self.assertEqual(sequence, 4)

    def test_expired_worker_cannot_commit_after_replacement(self):
        started, resume = Event(), Event()

        def provider(*args, **kwargs):
            if args[2] == "Expired":
                started.set()
                if not resume.wait(10):
                    raise TimeoutError("Test did not release provider")
            return self.reply

        request_id = uuid4()
        with patch.object(app.ai, "chat", side_effect=provider), ThreadPoolExecutor() as pool:
            process = pool.submit(self.send, "Expired", request_id)
            try:
                self.assertTrue(started.wait(10))
                with app.db() as conn:
                    conn.execute("UPDATE tutor_leases SET expires=0 WHERE branch=?", (self.key,))
                committed = self.send("Replacement")
            finally:
                resume.set()
            with self.assertRaises(HTTPException) as expired:
                process.result(timeout=10)
            self.assertEqual(expired.exception.status_code, 409)
            self.assertEqual(app.get(self.key), committed)
            self.assertEqual([message["text"] for message in committed], ["Replacement", "19.62 m"])

    def test_provider_failure_releases_reservation_and_keeps_transcript(self):
        request_id = uuid4()
        with patch.object(app.ai, "chat", side_effect=[HTTPException(503), self.reply]):
            with self.assertRaises(HTTPException):
                self.send("Retry me", request_id)
            self.assertIsNone(app.get(self.key))
            self.assertEqual(len(self.send("Retry me", request_id)), 2)

    def test_summary_failure_and_persisted_prefix(self):
        history = []
        for index in range(6):
            history += [{"role": "user", "text": f"Question {index}"}, self.reply]
        history[1] = {**self.reply, "traces": [{"tool": "simulate_motion",
                      "inputs": {"acceleration": 9.81, "velocity": 0, "duration": 2},
                      "output": {"s": 19.62, "v": 19.62, "t": 2}}]}
        app.put(self.key, history)
        budget = app.tutor_context.Budget("openai", app.ai.MODEL)
        context = {"lesson_version": self.doc["version"]}

        def load(messages, required=context):
            return app.tutor_context.WorkingContext(
                app.db, self.rid, self.tid, self.branch, required, [], messages, budget)

        def fits(ctx, recent):
            return len(recent) <= 4

        def summary_size(prefix):
            return len(prefix["turns"]) <= 2

        summary = {"text": "The first two questions were covered."}
        state = load(history)
        state.compact(fits, summary_size, lambda _: summary)
        lease = app.chat_state.Send(app.db, self.key, uuid4(), "Next", False)
        lease.reserve()
        committed = lease.commit({"role": "user", "text": "Next"}, self.reply, state.pending)
        reopened = load(committed)
        self.assertEqual((reopened.covered, reopened.summary), (4, summary))

        def unavailable(prefix):
            self.assertEqual(prefix["covered_through"], 4)
            self.assertEqual([turn["through"] for turn in prefix["turns"]], [6, 8])
            raise HTTPException(502)

        reopened.compact(fits, summary_size, unavailable)
        self.assertIsNone(reopened.pending)
        packed, recent = reopened.pack(fits)
        self.assertEqual(packed["older_summary"], {"covered_through": 4, **summary})
        observed = packed["verified_results"][0]
        self.assertEqual((observed["message_sequence"], observed["values"]["s"], observed["units"]["s"]),
                         (2, 19.62, "m"))
        self.assertEqual(recent, committed[-4:])
        self.assertIsNone(load(committed, {"lesson_version": "different"}).summary)

    def test_oversized_question_never_reaches_provider(self):
        with patch.dict(os.environ, {"STUDY_BOUNDED_CONTEXT": "1", "STUDY_TUTOR_CONTEXT_WINDOW": "9000",
                                     "STUDY_TUTOR_MODEL_WINDOWS": "{}"}), patch.object(app.ai, "client") as sdk:
            with TestClient(app.app) as client:
                response = client.post(self.path, json={"text": "a" * 11000},
                                       headers={"X-Study-Language": "en"})
            self.assertEqual(response.status_code, 422)
            self.assertIn("Shorten your question", response.json()["detail"])
            sdk.return_value.responses.create.assert_not_called()
        self.assertIsNone(app.get(self.key))

if __name__=="__main__":
    unittest.main()

