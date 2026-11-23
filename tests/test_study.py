import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing
from copy import deepcopy
from pathlib import Path
from subprocess import CompletedProcess, run
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
from openai.types.responses import ResponseFunctionToolCall

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
        self.assertIn("Hãy nhập một số và đơn vị phù hợp.", run.call_args.kwargs["input"])
        self.assertIn("quiz.0 (value_error)", logs.output[0])
        self.assertNotIn("p = -6 kg", logs.output[0])
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


class MemoryMigration(unittest.TestCase):
    def test_legacy_upgrade_repeat_and_restore(self):
        records = {
            "progress:physics:free-fall": {"0": [{"answer": "1962 cm", "correct": True, "explanation": "Conversion"}]},
            "thread:physics:free-fall:main": [{"role": "user", "text": "Legacy question"}],
        }
        summary = ("local", "physics", "free-fall", "old-version", "main", 1, 2, '{"text":"Older turns"}')
        for version in (0, 1, 2):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as folder:
                study = Path(folder) / "study"
                study.mkdir()
                road = study / "kept-road"
                road.mkdir()
                saved_road = road / "roadmap.json"
                saved_road.write_bytes(b'{"title":"Saved roadmap"}')
                with closing(sqlite3.connect(study / "study.sqlite")) as conn, conn:
                    conn.execute("CREATE TABLE records (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                    conn.executemany("INSERT INTO records VALUES (?,?)", [(k, json.dumps(v)) for k, v in records.items()])
                    if version >= 1:
                        app.chat_state.migrate(conn)
                        conn.execute("PRAGMA user_version=1")
                        conn.execute("INSERT INTO tutor_summaries VALUES (?,?,?,?,?,?,?,?)", summary)
                    if version == 2:
                        app.learner_memory.migrate(conn)
                        app.learner_memory.set_enabled(conn, True)
                        app.learner_memory.create(conn, "preference", "Keep this memory across migration")
                        conn.execute("PRAGMA user_version=2")
                restored = Path(folder) / "restored"
                for directory in (study, study, restored):
                    if directory == restored:
                        shutil.copytree(study, restored)
                    result = run([sys.executable, "-c", "import backend.main"],
                                 env={**os.environ, "STUDY_DATA": str(directory)}, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    with closing(sqlite3.connect(directory / "study.sqlite")) as conn:
                        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 3)
                        for key, value in records.items():
                            row = conn.execute("SELECT value FROM records WHERE key=?", (key,)).fetchone()
                            self.assertEqual(json.loads(row[0]), value)
                        if version >= 1:
                            self.assertEqual(conn.execute("SELECT * FROM tutor_summaries").fetchone(), summary)
                        if version == 2:
                            self.assertEqual(conn.execute("SELECT statement, revision FROM learner_memories").fetchall(),
                                             [("Keep this memory across migration", 1)])
                        self.assertEqual(conn.execute("SELECT * FROM learner_memory_vectors").fetchall(), [])
                    self.assertEqual((directory / "kept-road" / "roadmap.json").read_bytes(), saved_road.read_bytes())

    def test_failed_migration_rolls_back_schema_and_version(self):
        with tempfile.TemporaryDirectory() as folder:
            study = Path(folder)
            script = """
from unittest.mock import patch
from backend import learner_memory

def fail(conn):
    conn.execute('CREATE TABLE partial_migration (id INTEGER)')
    raise RuntimeError('injected migration failure')

with patch.object(learner_memory, 'migrate', fail):
    import backend.main
"""
            with closing(sqlite3.connect(study / "study.sqlite")) as conn, conn:
                conn.execute("CREATE TABLE records (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                conn.execute("INSERT INTO records VALUES ('old', '123')")
            result = run([sys.executable, "-c", script], env={**os.environ, "STUDY_DATA": folder},
                         capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("injected migration failure", result.stderr)
            with closing(sqlite3.connect(study / "study.sqlite")) as conn:
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT * FROM records").fetchall(), [("old", "123")])
                self.assertEqual(conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [("records",)])


class FakeMemoryEncoder:
    def __init__(self, identifier="scripted-v1"):
        self.metadata = {"id": identifier, "dimension": 2, "threshold": 0.6}
        self.status = "ready"
        self.requests = []

    def start(self):
        pass

    def close(self):
        pass

    def encode(self, texts, *, query, deadline):
        if query:
            self.requests.extend(texts)
        return [[0.0, -1.0] if "unrelated" in text else [1.0, 0.0] for text in texts]


class LearnerMemory(unittest.TestCase):
    base = "/api/memories"

    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(app, "DATA", Path(directory)))
        with app.db() as conn:
            conn.execute("CREATE TABLE records (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            app.chat_state.migrate(conn)
            app.learner_memory.migrate(conn)
            app.memory_retrieval.migrate(conn)
            conn.execute("PRAGMA user_version=3")
        self.client = TestClient(app.app, headers={"X-Study-Language": "en"})
        self.addCleanup(self.client.close)
        self.rid, self.tid, self.doc = self.seed_lesson()
        self.quiz = f"/api/quiz/{self.rid}/{self.tid}"

    def seed_lesson(self):
        road = app.commit(Roadmap.model_validate(ROAD))
        rid, tid = road["id"], road["chapters"][0]["topics"][0]["id"]
        doc = deepcopy(SAMPLE)
        doc["quiz"].extend({"kind": "number", "prompt": prompt, "answer": answer, "choices": [], "explanation": answer}
                           for prompt, answer in [("How far?", "42 m"), ("How long?", "7 s"), ("Distance?", "9 m")])
        doc["version"] = uuid4().hex
        app.put(f"lesson:{rid}:{tid}", doc)
        return rid, tid, doc

    def capture(self, enabled):
        response = self.client.put(f"{self.base}/capture", json={"enabled": enabled})
        self.assertEqual(response.status_code, 200, response.text)

    def memories(self):
        response = self.client.get(self.base)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["memories"]

    def submit(self, question, answer, attempt_id=None):
        return self.client.post(self.quiz, json={"question": question, "answer": answer,
                                                "attempt_id": attempt_id or str(uuid4())})

    def attempt(self, question, answer):
        response = self.submit(question, answer)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()[str(question)][-1]

    def process(self):
        app.learner_memory.process_pending(app.db)

    def restart_memories(self, wait_for=""):
        script = """
import json
import sys
from time import monotonic, sleep
from fastapi.testclient import TestClient
from backend.main import app

with TestClient(app) as client:
    deadline = monotonic() + 8
    while True:
        memories = client.get('/api/memories').json()['memories']
        if not sys.argv[1] or any(m['status'] == sys.argv[1] for m in memories) or monotonic() >= deadline:
            print(json.dumps(memories))
            break
        sleep(0.05)
"""
        result = run([sys.executable, "-c", script, wait_for],
                     env={**os.environ, "STUDY_DATA": str(app.DATA)}, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_opt_in_and_explicit_memories_shared_without_tutor_access(self):
        self.assertFalse(self.client.get(self.base).json()["enabled"])
        self.attempt(0, "19.62 s")
        self.process()
        self.assertEqual(self.memories(), [])
        self.capture(True)
        self.assertEqual(self.client.get(f"/api/lesson/{self.rid}/{self.tid}").status_code, 200)
        with patch.object(app.ai, "structured", return_value=ROAD):
            draft = self.client.post("/api/drafts", json={"subject": "Physics", "goal": "Draft-only goal",
                                                         "level": "New", "schedule": "1 hour"}).json()
        self.assertEqual(self.client.post("/api/roads", json=draft).status_code, 200)
        self.process()
        self.assertEqual(self.memories(), [])
        for kind, statement in (("goal", "Chuyển đổi đơn vị"), ("preference", "Explain with a diagram")):
            response = self.client.post(self.base, json={"kind": kind, "statement": statement},
                                        headers={"X-Study-Language": "vi" if kind == "goal" else "en"})
            self.assertEqual(response.status_code, 200, response.text)
        for language in ("vi", "en"):
            memories = self.client.get(self.base, headers={"X-Study-Language": language}).json()["memories"]
            self.assertEqual({(m["kind"], m["statement"]) for m in memories},
                             {("goal", "Chuyển đổi đơn vị"), ("preference", "Explain with a diagram")})
        self.assertEqual({(m["kind"], m["statement"]) for m in self.restart_memories()},
                         {("goal", "Chuyển đổi đơn vị"), ("preference", "Explain with a diagram")})
        with patch.object(app.ai, "chat", return_value={"role": "assistant", "text": "Reply"}) as provider:
            self.assertEqual(self.client.post(f"/api/chat/{self.rid}/{self.tid}/main", json={"text": "Explain."}).status_code, 200)
            self.assertNotIn("Explain with a diagram", str(provider.call_args))
            self.assertNotIn("Chuyển đổi đơn vị", str(provider.call_args))
        self.capture(False)
        self.attempt(2, "42 s")
        self.capture(True)
        self.process()
        self.assertEqual(len(self.memories()), 2)

    def test_memory_scope_is_one_roadmap_and_one_owner(self):
        self.capture(True)
        self.attempt(0, "19.62 s")
        rid, tid, _ = self.seed_lesson()
        other = self.client.post(f"/api/quiz/{rid}/{tid}", json={"question": 2, "answer": "42 s"})
        self.assertEqual(other.status_code, 200, other.text)
        self.process()
        memories = self.memories()
        self.assertEqual({(m["roadmap_id"], m["status"]) for m in memories},
                         {(self.rid, "tentative"), (rid, "tentative")})
        response = self.client.post(self.base, json={"kind": "preference", "statement": "Private fixture"})
        self.assertEqual(response.status_code, 200, response.text)
        private = next(m for m in self.memories() if m["kind"] == "preference")
        with app.db() as conn:
            conn.execute("UPDATE learner_memories SET owner='other' WHERE id=?", (private["id"],))
        self.assertEqual(len(self.memories()), 2)
        path = f"{self.base}/{private['id']}"
        self.assertEqual(self.client.patch(path, json={"statement": "Edited", "revision": private["revision"]}).status_code, 404)
        self.assertEqual(self.client.delete(path, params={"revision": private["revision"]}).status_code, 404)

    def test_unit_diagnostics_dedup_and_resolution(self):
        self.capture(True)
        first = self.attempt(0, "19.62 s")
        attempt_id = first["attempt_id"]
        self.assertEqual(self.submit(0, "19.62 s", attempt_id).json()["0"], [first])
        self.assertEqual(self.submit(0, "19.63 s", attempt_id).status_code, 409)
        self.assertEqual(self.submit(2, "19.62 s", attempt_id).status_code, 409)
        latest = self.attempt(0, "19.62 kg")
        self.attempt(2, "41 m")
        self.attempt(1, self.doc["quiz"][1]["choices"][0])
        self.assertEqual(self.submit(2, "invalid").status_code, 422)
        self.process()
        candidate, = self.memories()
        self.assertEqual((candidate["status"], candidate["diagnostic"], candidate["roadmap_id"]),
                         ("tentative", "incompatible_unit", self.rid))
        self.assertEqual([ref["attempt_id"] for ref in candidate["evidence"]], [latest["attempt_id"]])
        other = self.attempt(2, "42 s")
        self.attempt(3, "7 m")
        self.attempt(4, "9")
        self.process()
        recurring, = [m for m in self.memories() if m["status"] == "recurring"]
        self.assertEqual(recurring["id"], candidate["id"])
        self.assertEqual({ref["attempt_id"] for ref in recurring["evidence"]}, {latest["attempt_id"], other["attempt_id"]})
        self.assertEqual({m["diagnostic"] for m in self.memories()}, {"incompatible_unit", "missing_unit"})
        for question, answer, status in [(0, "1962 cm", "tentative"), (2, "42 m", "resolved")]:
            self.assertTrue(self.attempt(question, answer)["correct"])
            self.process()
            self.assertEqual(next(m["status"] for m in self.memories() if m["id"] == recurring["id"]), status)

    def test_concurrent_retry_and_worker_recovery(self):
        self.capture(True)
        attempt_id = str(uuid4())
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = (pool.submit(self.submit, 0, "19.62 s", attempt_id) for _ in range(2))
            expected = first.result(timeout=10)
            self.assertEqual(expected.status_code, 200)
            self.assertEqual(expected.json(), second.result(timeout=10).json())
            self.assertEqual(len(expected.json()["0"]), 1)
        with patch.object(app.learner_memory, "apply_event", side_effect=RuntimeError("synthetic processor failure")):
            with self.assertLogs(app.learner_memory.__name__, level="WARNING") as captured:
                self.process()
            self.assertIn("RuntimeError", captured.output[0])
            self.assertNotIn("synthetic processor failure", captured.output[0])
            self.assertEqual(self.memories(), [])
            with app.db() as conn:
                self.assertEqual(conn.execute("SELECT failures FROM learner_memory_pending").fetchall(), [(1,)])
        self.attempt(2, "42 s")
        memory, = self.restart_memories("recurring")
        self.assertEqual(memory["status"], "recurring")
        self.assertEqual(len(memory["evidence"]), 2)
        self.attempt(0, "1962 cm")
        corrected = self.client.patch(f"{self.base}/{memory['id']}",
                                      json={"statement": "I can now convert length units", "revision": memory["revision"]})
        self.assertEqual(corrected.status_code, 200, corrected.text)
        self.assertEqual(self.client.post(self.base, json={"kind": "preference", "statement": "Explain first"}).status_code, 200)
        preference = next(m for m in self.memories() if m["kind"] == "preference")
        response = self.client.patch(f"{self.base}/{preference['id']}",
                                     json={"statement": "Show the formula first", "revision": preference["revision"]})
        self.assertEqual(response.status_code, 200, response.text)
        self.process()
        self.assertEqual({m["statement"] for m in self.memories()}, {"I can now convert length units", "Show the formula first"})
        self.attempt(3, "7 m")
        self.capture(False)
        self.capture(True)
        self.process()
        self.assertEqual(len(self.memories()), 2)

    def test_source_conflict_forget_replay_and_resume(self):
        self.capture(True)
        first = self.attempt(0, "19.62 s")
        self.attempt(2, "42 s")
        self.process()
        memory, = self.memories()
        path = f"{self.base}/{memory['id']}"
        source = f"{path}/evidence/{first['attempt_id']}"
        self.attempt(0, "1962 cm")
        response = self.client.get(source, headers={"X-Study-Language": "vi"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual((response.json()["answer"], response.json()["correct"]), ("19.62 s", False))
        self.assertEqual(self.client.get(f"{path}/evidence/{uuid4()}").status_code, 404)
        key = f"lesson:{self.rid}:{self.tid}"
        app.put(key, {**self.doc, "version": uuid4().hex})
        self.assertIn(self.client.get(source).status_code, (404, 409))
        app.put(key, self.doc)
        self.assertEqual(self.client.patch(path, json={"statement": "Stale", "revision": memory["revision"] + 1}).status_code, 409)
        self.assertEqual(self.client.delete(path, params={"revision": memory["revision"] + 1}).status_code, 409)
        self.assertEqual(self.client.delete(path, params={"revision": memory["revision"]}).status_code, 200)
        self.assertEqual(self.submit(0, "19.62 s", first["attempt_id"]).status_code, 200)
        with app.db() as conn:
            conn.execute("""INSERT INTO learner_memory_pending (owner, submission_seq, diagnostic, dimension, expected_revision)
                SELECT owner, seq, ?, ?, ? FROM quiz_submissions WHERE id=?""",
                         (memory["diagnostic"], memory["dimension"], memory["revision"], first["attempt_id"]))
        new = self.attempt(0, "19.62 s")
        self.attempt(2, "42 s")
        self.process()
        self.assertEqual(self.restart_memories(), [])
        self.assertEqual(self.client.get(source).status_code, 404)
        with app.db() as conn:
            self.assertIsNone(app.learner_memory.record(conn, memory["id"], memory["revision"]))
        self.assertEqual(self.client.post(f"{self.base}/resume", json={"attempt_id": first["attempt_id"]}).status_code, 409)
        response = self.client.post(f"{self.base}/resume", json={"attempt_id": new["attempt_id"]})
        self.assertEqual(response.status_code, 200, response.text)
        self.process()
        replacement, = self.memories()
        self.assertNotEqual(replacement["id"], memory["id"])
        self.assertEqual(replacement["status"], "tentative")
        self.assertEqual([ref["attempt_id"] for ref in replacement["evidence"]], [new["attempt_id"]])
        self.assertEqual(app.read(self.rid, self.tid)["progress"]["0"][0], first)
        self.assertEqual(self.client.post(self.base, json={"kind": "preference", "statement": "Forget this preference"}).status_code, 200)
        preference = next(m for m in self.memories() if m["kind"] == "preference")
        self.assertEqual(self.client.delete(f"{self.base}/{preference['id']}", params={"revision": preference["revision"]}).status_code, 200)
        self.assertNotIn(preference["id"], {m["id"] for m in self.restart_memories()})

    def add_preference(self, text):
        response = self.client.post(self.base, json={"kind": "preference", "statement": text})
        self.assertEqual(response.status_code, 200, response.text)
        return next(item for item in response.json()["memories"] if item["statement"] == text)

    def retrieval(self, encoder, question="Giải thích cách đổi đơn vị", note=None):
        return app.memory_retrieval.retrieve(app.db, encoder, self.rid, {"title": "Distance"}, note, question)[1]

    def test_v2_index_filters_scope_revision_and_provenance(self):
        self.capture(True)
        preference = self.add_preference("Use a diagram to explain units")
        self.attempt(3, "7 m")
        self.process()
        tentative, = [item for item in self.memories() if item["status"] == "tentative"]
        attempts = [self.attempt(0, "19.62 s")["attempt_id"], self.attempt(2, "42 s")["attempt_id"]]
        self.process()
        recurring, = [item for item in self.memories() if item["status"] == "recurring"]
        encoder = FakeMemoryEncoder()
        app.memory_retrieval.sync(app.db, encoder)
        with app.db() as conn:
            exemplar = conn.execute("SELECT vector FROM learner_memory_vectors WHERE memory_id=?",
                                    (preference["id"],)).fetchone()[0]
            ids = ["foreign", "elsewhere", "sibling", "stale", "resolved", "deleted"]
            fields = [
                ("other", ids[0], "confirmed", None),
                ("local", ids[1], "confirmed", "different-roadmap"),
                ("local", ids[2], "confirmed", None),
                ("local", ids[3], "confirmed", None),
                ("local", ids[4], "resolved", None),
            ]
            for owner, memory_id, status, roadmap in fields:
                conn.execute("""INSERT INTO learner_memories
                    (owner,id,kind,statement,status,revision,language,roadmap_id,created_at,updated_at)
                    VALUES (?,?,?,'Distinct private fixture',?,2,'en',?,'2099','2099')""",
                             (owner, memory_id, "branch_fact" if memory_id == "sibling" else "preference", status, roadmap))
            vectors = [("other" if index == 0 else "local", memory_id, 1 if index == 3 else 2,
                        encoder.metadata["id"], 2, exemplar) for index, memory_id in enumerate(ids)]
            vectors.append(("local", tentative["id"], tentative["revision"], encoder.metadata["id"], 2, exemplar))
            conn.executemany("INSERT INTO learner_memory_vectors VALUES (?,?,?,?,?,?)", vectors)
        selected = self.retrieval(encoder, note={"quote": "ACTIVE SELECTION " + "x" * 512})
        self.assertEqual({item["id"] for item in selected}, {preference["id"], recurring["id"]})
        self.assertEqual(len(encoder.requests[0].splitlines()[-1]), 256)
        quiz_item = next(item for item in selected if item["id"] == recurring["id"])
        self.assertEqual(set(quiz_item["provenance"]["attempt_ids"]), set(attempts))
        path = f"{self.base}/{recurring['id']}"
        item = self.client.get(path, params={"revision": recurring["revision"]}).json()
        self.assertEqual({ref["attempt_id"] for ref in item["evidence"]}, set(attempts))
        self.assertEqual(self.retrieval(encoder, "unrelated algebra"), [])
        app.put(f"lesson:{self.rid}:{self.tid}", {**self.doc, "version": uuid4().hex})
        self.assertEqual({item["id"] for item in self.retrieval(encoder)}, {preference["id"]})
        self.assertEqual(self.client.get(path, params={"revision": recurring["revision"]}).status_code, 404)

    def test_v2_restart_rebuild_and_concurrent_revision_changes(self):
        self.capture(True)
        items = [self.add_preference(f"Original preference {index}") for index in range(10)]
        old = FakeMemoryEncoder()
        for _ in range(2):
            app.memory_retrieval.sync(app.db, old)
        self.assertTrue(self.retrieval(old))
        replacement = FakeMemoryEncoder("scripted-v2")
        app.memory_retrieval.sync(app.db, replacement)
        self.assertEqual(self.retrieval(replacement), [])
        update, forget = sorted(items, key=lambda item: item["id"])[-2:]

        def mutate_during_encoding(texts, *, query, deadline):
            self.assertEqual(self.client.patch(f"{self.base}/{update['id']}",
                json={"statement": "Updated preference", "revision": update["revision"]}).status_code, 200)
            self.assertEqual(self.client.delete(f"{self.base}/{forget['id']}",
                params={"revision": forget["revision"]}).status_code, 200)
            return [[1.0, 0.0] for _ in texts]

        restarted = FakeMemoryEncoder(replacement.metadata["id"])
        with patch.object(restarted, "encode", side_effect=mutate_during_encoding):
            app.memory_retrieval.sync(app.db, restarted)
        self.assertEqual(self.retrieval(restarted), [])
        app.memory_retrieval.sync(app.db, restarted)
        self.assertTrue(self.retrieval(restarted))
        with app.db() as conn:
            vectors = conn.execute("SELECT memory_id, revision, encoder_id FROM learner_memory_vectors").fetchall()
        self.assertEqual(len(vectors), 9)
        self.assertTrue(all(encoder_id == restarted.metadata["id"] for _, _, encoder_id in vectors))
        self.assertIn((update["id"], update["revision"]+1, restarted.metadata["id"]), vectors)
        self.assertNotIn(forget["id"], {memory for memory, _, _ in vectors})

    def test_v3_provider_budget_refs_retry_and_transcript(self):
        self.capture(True)
        memory = self.add_preference("Explain with drawings")
        self.add_preference("a" * 1200)
        encoder = FakeMemoryEncoder()
        reply_text = "The old memory-assisted answer is visible only in the reader."
        expected = [{"id": memory["id"], "revision": memory["revision"]}]
        model = "scripted-codex"
        tool = ResponseFunctionToolCall(type="function_call", name="calculator",
            call_id="phase3-call", arguments='{"expression":"0.5*9.81*2**2"}')

        with patch.dict(os.environ, {"STUDY_BOUNDED_CONTEXT": "1", "STUDY_TUTOR_CONTEXT_WINDOW": "12500",
                                     "STUDY_TUTOR_MODEL_WINDOWS": "{}"}), patch.object(app, "memory_encoder", encoder):
            app.memory_retrieval.sync(app.db, encoder)
            for provider in ("openai", "codex"):
                with self.subTest(provider=provider), ExitStack() as mocks:
                    payloads = []
                    phase = ["tool", "answer"]
                    mocks.enter_context(patch.object(app, "ai_settings", return_value={
                        "provider": provider, "codex_model": model}))

                    def openai(**request):
                        self.assertLessEqual(app.tutor_context.json_bytes(request), 12500-6144)
                        prefix = app.prompt("providers/openai-context") + " "
                        context = json.loads(request["input"][0]["content"].removeprefix(prefix))
                        payloads.append((context, str(request["input"])))
                        return SimpleNamespace(usage=None, output=[tool] if phase.pop(0) == "tool" else [],
                                               output_text=reply_text)

                    def codex(schema, schema_text, stdin, search, codex_model, usage, **kwargs):
                        self.assertLessEqual(len(stdin.encode())+len(schema_text.encode()),
                                             int(os.environ["STUDY_TUTOR_CONTEXT_WINDOW"])-6144)
                        context = json.loads(stdin.rsplit("\n", 1)[-1])
                        payloads.append((context["lesson"], stdin))
                        return dict(action="calculator" if phase.pop(0) == "tool" else "answer",
                                    arguments_json=tool.arguments, text=reply_text, sources=[])

                    sdk = mocks.enter_context(patch.object(app.ai, "client")).return_value
                    sdk.with_options.return_value = sdk
                    sdk.responses.create.side_effect = openai
                    mocks.enter_context(patch.object(app.providers, "run_codex", side_effect=codex))
                    chat = f"/api/chat/{self.rid}/{self.tid}/question-{uuid4().hex}"
                    request = {"text": "Giải thích cách đổi đơn vị", "request_id": str(uuid4())}
                    first = self.client.post(chat, json=request)
                    self.assertEqual(first.status_code, 200, first.text)
                    saved = first.json()[-1]
                    self.assertEqual(saved["memory_refs"], expected)
                    self.assertAlmostEqual(saved["traces"][0]["output"]["result"], 19.62)
                    self.assertEqual(len(payloads), 2)
                    for context, _ in payloads:
                        matches = context["learner_memories"]
                        self.assertEqual([{k: item[k] for k in ("id", "revision")} for item in matches], expected)
                        self.assertLessEqual(app.tutor_context.json_bytes({"learner_memories": matches}), 1024)
                    if provider == "openai":
                        self.assertEqual([call.kwargs for call in sdk.with_options.call_args_list],
                                         [{"max_retries": 0}, {"max_retries": 0}])
                    self.assertEqual(self.client.post(chat, json=request).json(), first.json())
                    self.assertEqual(len(payloads), 2)
                    self.capture(False)
                    phase.append("answer")
                    follow = self.client.post(chat, json={"text":"Follow-up while paused"})
                    self.assertEqual(follow.status_code, 200, follow.text)
                    self.assertNotIn("learner_memories", payloads[-1][0])
                    self.assertNotIn(reply_text, payloads[-1][1])
                    self.assertNotIn("memory_refs", follow.json()[-1])
                    self.assertEqual(follow.json()[1], saved)
                    self.capture(True)
                    if provider == "codex":
                        phase.append("answer")
                        with patch.dict(os.environ, {"STUDY_TUTOR_CONTEXT_WINDOW": "10500"}):
                            tighter = self.client.post(f"/api/chat/{self.rid}/{self.tid}/question-{uuid4().hex}",
                                                       json=request)
                        self.assertEqual(tighter.status_code, 200, tighter.text)
                        self.assertNotIn("learner_memories", payloads[-1][0])
                        self.assertNotIn("memory_refs", tighter.json()[-1])

    def test_v3_revocation_during_provider_call_aborts_and_same_id_retries(self):
        self.capture(True)
        encoder = FakeMemoryEncoder()
        calls = []

        def provider(schema, schema_text, stdin, search, model, usage, **kwargs):
            payload = json.loads(stdin.rsplit("\n", 1)[-1])
            calls.append(payload["lesson"].get("learner_memories", []))
            if len(calls) == 1:
                removed = self.client.delete(f"{self.base}/{memory['id']}", params={"revision": memory["revision"]})
                self.assertEqual(removed.status_code, 200, removed.text)
                return {"action":action, "text":"Reply", "arguments_json":'{"expression":"2+3"}', "sources":[]}
            return {"action":"answer", "text":"Reply", "arguments_json":"{}", "sources":[]}

        with patch.dict(os.environ, {"STUDY_BOUNDED_CONTEXT": "1", "STUDY_TUTOR_MODEL_WINDOWS": "{}",
                                     "STUDY_TUTOR_CONTEXT_WINDOW": "12500"}), \
                patch.object(app, "memory_encoder", encoder), \
                patch.object(app, "ai_settings", return_value={"provider": "codex"}), \
                patch.object(app.providers, "run_codex", side_effect=provider):
            for action in ("answer", "calculator"):
                with self.subTest(action=action):
                    memory = self.add_preference("Use diagrams")
                    request = {"text": "Explain unit conversion", "request_id": str(uuid4())}
                    chat = f"/api/chat/{self.rid}/{self.tid}/question-{uuid4().hex}"
                    calls.clear()
                    app.memory_retrieval.sync(app.db, encoder)
                    stale = self.client.post(chat, json=request)
                    self.assertEqual(stale.status_code, 409, stale.text)
                    self.assertEqual(stale.headers["Retry-After"], "1")
                    self.assertEqual(len(calls), 1)
                    self.assertTrue(calls[0])
                    self.assertEqual(self.client.get(chat).json(), [])
                    retry = self.client.post(chat, json=request)
                    self.assertEqual(retry.status_code, 200, retry.text)
                    self.assertEqual(calls[1], [])
                    self.assertEqual(len(retry.json()), 2)
                    self.assertNotIn("memory_refs", retry.json()[-1])

    def test_v1_optional_encoder_errors_and_timeouts_keep_chat_and_grading(self):
        self.capture(True)
        encoder = FakeMemoryEncoder()
        self.add_preference("Use diagrams")
        chat = f"/api/chat/{self.rid}/{self.tid}/main"

        def slow_encode(texts, *, query, deadline):
            sleep(max(0, deadline-monotonic()) + 0.01)
            return [[1.0, 0.0] for _ in texts]

        with patch.dict(os.environ, {"STUDY_BOUNDED_CONTEXT": "1"}), patch.object(app, "memory_encoder", encoder), \
                patch.object(app.ai, "chat", return_value={"role":"assistant", "text":"Fallback reply"}) as tutor:
            app.memory_retrieval.sync(app.db, encoder)
            for status in ("missing", "error", "ready"):
                with self.subTest(status=status), patch.object(encoder, "status", status), \
                        patch.object(encoder, "encode", side_effect=slow_encode):
                    if status != "ready":
                        self.assertEqual(self.client.get(self.base).json()["encoder_status"], status)
                    response = self.client.post(chat, json={"text": "Explain without optional retrieval"})
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(tutor.call_args.kwargs["working"].memories, [])
                    self.assertEqual(response.json()[-1]["text"], "Fallback reply")
            self.assertTrue(self.attempt(0, "1962 cm")["correct"])

if __name__=="__main__":
    unittest.main()

