"""Scripted provider-boundary and chat reservation checks for Phase 4."""

from collections import deque
from contextlib import ExitStack
import json
import os
from pathlib import Path
from subprocess import CompletedProcess, TimeoutExpired
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient
from openai import OpenAI


SOURCE = {"url": "https://example.test/gravity", "title": "Gravity"}
LESSON = "/api/lesson/physics/free-fall"
CHAT = "/api/chat/physics/free-fall/"


def action(target, arguments=None):
    return target, json.dumps(arguments or {})


def step(text="", *, calls=(), sources=(), search=None, search_count=1):
    return dict(text=text, calls=calls, sources=sources, search=search, search_count=search_count)


class Script:
    def __init__(self, app, stack, provider, *responses):
        self.provider = provider
        self.pending = deque(responses)
        self.requests = []
        self.app = app
        self.before_response = None
        self.settings = stack.enter_context(patch.object(app, "ai_settings", side_effect=self.selected_settings))
        client = httpx.Client(transport=httpx.MockTransport(self.openai))
        sdk = stack.enter_context(OpenAI(api_key="synthetic", http_client=client))
        stack.enter_context(patch.object(app.ai, "client", return_value=sdk))
        stack.enter_context(patch.object(app.providers.shutil, "which", return_value="codex-fixture"))
        stack.enter_context(patch.object(app.providers.subprocess, "run", side_effect=self.codex))

    def selected_settings(self):
        return {"provider": self.provider, "codex_model": "fixture-model"}

    def next(self, request, timeout):
        self.requests.append((request, timeout))
        if self.before_response:
            self.before_response()
        return self.pending.popleft()

    def openai(self, http_request):
        request = json.loads(http_request.content)
        item = self.next(request, http_request.extensions["timeout"]["read"])
        if item == "timeout":
            raise httpx.ReadTimeout("synthetic timeout", request=http_request)
        output = []
        if item["search"]:
            output.append(dict(type="web_search_call", id="ws_1", status=item["search"]))
        for index, (name, arguments) in enumerate(item["calls"]):
            key = f"{len(self.requests)}_{index}"
            output.append(dict(type="function_call", id=f"fc_{key}", call_id=f"call_{key}",
                               status="completed", name=name, arguments=arguments))
        if item["text"]:
            citations = [dict(source, type="url_citation", start_index=0, end_index=1)
                         for source in item["sources"]]
            output.append(dict(type="message", id="msg_1", status="completed", role="assistant",
                               content=[dict(type="output_text", text=item["text"], annotations=citations)]))
        return httpx.Response(200, json={"id": "resp_1", "object": "response", "status": "completed", "output": output})

    def codex(self, args, **options):
        if "login" in args:
            return CompletedProcess(args, 0, b"", b"")
        schema_path = Path(args[args.index("--output-schema") + 1])
        model = args[args.index("--model") + 1]
        search = 'web_search="live"' in args
        schema = json.loads(schema_path.read_bytes())["title"]
        context = json.loads(options["input"].rsplit("\n", 1)[-1])
        item = self.next(dict(schema=schema, model=model, search=search, context=context), options["timeout"])
        if item == "timeout":
            raise TimeoutExpired(args, options["timeout"])
        if schema == "AgentStep":
            [(target, arguments)] = item["calls"] or [("answer", "{}")]
            message = dict(action=target, arguments_json=arguments, text=item["text"], sources=item["sources"])
        else:
            message = json.loads(item["text"])
        events = [dict(type="item.completed" if item["search"] == "completed" else "item.started",
                       item={"type": "web_search", "id": f"ws_{index}", "query": "gravity"})
                  for index in range(item["search_count"] if item["search"] else 0)]
        events.append(dict(type="item.completed", item={"type": "agent_message", "text": json.dumps(message)}))
        return CompletedProcess(args, 0, "\n".join(map(json.dumps, events)), "")

    def observations(self, index=-1):
        request, _ = self.requests[index]
        if "context" in request:
            return [item["output"] for item in request["context"]["results"]]
        return [json.loads(item["output"]) for item in request["input"] if item.get("type") == "function_call_output"]

    def search_flags(self):
        return [request["search"] if "search" in request
                else any(tool["type"] == "web_search" for tool in request.get("tools", []))
                for request, _ in self.requests]


class TutorAgent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stack = ExitStack()
        cls.addClassCleanup(stack.close)
        data = stack.enter_context(TemporaryDirectory(prefix="conceptlens-agent-tests-"))
        # The rest of the suite may have already imported the app with its own fixture.
        with patch.dict(os.environ, {"STUDY_DATA": data}):
            from backend import main as app
        cls.app = app
        stack.enter_context(patch.object(app, "DATA", Path(data)))
        with app.db() as conn:
            if not conn.execute("PRAGMA user_version").fetchone()[0]:
                conn.execute("CREATE TABLE records (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                app.chat_state.migrate(conn)
                app.learner_memory.migrate(conn)
                app.memory_retrieval.migrate(conn)
        app.write_road(dict(app.ROAD_EN, id="physics"))
        app.put("lesson:physics:free-fall", dict(app.SAMPLE_EN, version="tutor-agent-fixture"))

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {"STUDY_TUTOR_AGENT": "1", "STUDY_BOUNDED_CONTEXT": "0",
                                                       "STUDY_TUTOR_DEADLINE_SECONDS": "30",
                                                       "STUDY_TUTOR_CONTEXT_WINDOW": "20000",
                                                       "STUDY_TUTOR_MODEL_WINDOWS": "{}"}))
        self.client = TestClient(self.app.app, headers={"X-Study-Language": "en"})
        self.addCleanup(self.client.close)

    def chat(self, *, branch=None, text="Fixture tutor question", search=False, request_id=None, status=200):
        path = CHAT + (branch or f"question-{uuid4().hex}")
        payload = dict(text=text, search=search, request_id=request_id or str(uuid4()))
        response = self.client.post(path, json=payload)
        self.assertEqual(response.status_code, status, response.text)
        return response.json()[-1] if status == 200 else response.json()

    def test_v1_answer_and_clarification_skip_dispatch(self):
        for provider in ("openai", "codex"):
            clarify = step(calls=[action("clarify", {"text": "What is the initial velocity?"})])
            if provider == "codex":
                clarify["text"] = "What is the initial velocity?"
            with self.subTest(provider=provider), ExitStack() as stack:
                script = Script(self.app, stack, provider, step("Acceleration is a rate."), clarify)
                with self.assertLogs(self.app.tutor_agent.log, "INFO") as logs:
                    for text in ("Acceleration is a rate.", "What is the initial velocity?"):
                        self.assertEqual(self.chat(), dict(role="assistant", text=text, sources=[], traces=[]))
                self.assertEqual(len(script.requests), 2)
                self.assertEqual(script.search_flags(), [False, False])
                self.assertEqual(sum("steps=1 actions=0" in line for line in logs.output), 2)
                self.assertFalse(script.pending)

    def test_v2_native_batch_saved_snapshot_and_provider_switch(self):
        lesson = self.client.get(LESSON).json()["doc"]
        quote = lesson["illustrations"][0]["instruction"]
        note = self.client.post("/api/notes/physics/free-fall", json={
            "block": "i0", "version": lesson["version"], "start": 0, "end": len(quote.encode("utf-16-le")) // 2,
            "quote": quote, "snapshot": {"acceleration": 9.81, "velocity": 0, "duration": 4, "t": 2, "s": 19.62, "v": 19.62},
        })
        self.assertEqual(note.status_code, 200, note.text)
        branch = note.json()["id"]
        self.app.put("motion:physics:free-fall:0", {"params": {"acceleration": 5}, "points": [{"t": 1, "s": 2.5}], "index": 0})
        calc = action("calculator", {"expression": "1962/100"})
        motion = action("simulate_motion", {"acceleration": 5, "velocity": 10, "duration": 1, "use_snapshot": True})
        with patch.dict(os.environ, {"STUDY_BOUNDED_CONTEXT": "1"}), ExitStack() as stack:
            script = Script(self.app, stack, "openai", step(calls=[calc, motion]), step("19.62 m"),
                            step(calls=[motion]), step("The recorded result is 19.62 m."))
            result = self.chat(branch=branch, text="Use the saved selection.")
            self.assertEqual([trace["tool"] for trace in result["traces"]], ["calculator", "simulate_motion"])
            trace = result["traces"][1]
            self.assertEqual((trace["source"], trace["output"]["t"], trace["units"]["s"]), ("highlight", 2, "m"))
            self.assertAlmostEqual(trace["output"]["s"], 19.62)
            request = script.requests[1][0]
            outputs = [item for item in request["input"] if item.get("type") == "function_call_output"]
            self.assertEqual([item["call_id"] for item in outputs], ["call_1_0", "call_1_1"])
            script.provider = "codex"
            result = self.chat(branch=branch, text="Use the selected time again.")
            self.assertEqual(result["traces"][0], trace)
            context = script.requests[2][0]["context"]["lesson"]
            self.assertTrue(any(item["values"].get("s") == 19.62 for item in context["verified_results"]))
            self.assertEqual(context["simulation"]["values"]["t"], 2)
            self.assertFalse(script.pending)

    def test_v3_validation_recovery_repeat_and_caps(self):
        calc = action("calculator", {"expression": "2+3"})
        invalid = action("calculator", {"expression": 123})
        for provider in ("openai", "codex"):
            with self.subTest(provider=provider), ExitStack() as stack:
                script = Script(self.app, stack, provider, step(calls=[action("unknown_target")]), step(calls=[invalid]),
                                step(calls=[calc]), step(calls=[calc]), step("5"))
                handler = self.app.ai.TOOLS["calculator"]
                dispatch = stack.enter_context(patch.dict(self.app.ai.TOOLS))
                spy = stack.enter_context(patch.object(self.app.ai, "calculate", wraps=self.app.ai.calculate))
                with self.assertLogs(self.app.tutor_agent.log, "INFO") as logs:
                    reply = self.chat()
                self.assertEqual(spy.call_count, 1)
                self.assertEqual(len(reply["traces"]), 1)
                results = script.observations()
                self.assertEqual([item.get("error") for item in results],
                                 ["route_unavailable", "invalid_arguments", None, "repeated_action"])
                self.assertTrue(any("steps=5 actions=4" in line for line in logs.output))
                self.assertNotIn("Fixture tutor question", "\n".join(logs.output))
                dispatch["calculator"] = (handler[0], lambda _: {"result": float("inf")})
                script.pending.extend([step(calls=[calc]), step("Available result is invalid.")])
                self.assertEqual(self.chat()["traces"], [])
                self.assertEqual(script.observations(), [{"error": "invalid_tool_output"}])
                dispatch["calculator"] = handler
                script.pending.extend([step(calls=[("calculator", "{")]), step(calls=[invalid])])
                self.assertIn("limit", self.chat(status=502)["detail"])
                if provider == "openai":
                    script.pending.append(step(calls=[calc] * 7))
                    self.assertIn("limit", self.chat(status=502)["detail"])
                    self.assertEqual(spy.call_count, 1)
                script.pending.extend([step(calls=[action("unknown_target")])] * 6)
                with self.assertLogs(self.app.tutor_agent.log, "INFO") as limit_logs:
                    self.assertIn("limit", self.chat(status=502)["detail"])
                self.assertTrue(any("steps=6 actions=6" in line for line in limit_logs.output))
                self.assertFalse(script.pending)

    def test_v4_search_permission_completion_and_sources(self):
        for provider in ("openai", "codex"):
            with self.subTest(provider=provider), ExitStack() as stack:
                script = Script(self.app, stack, provider, step("No lookup", sources=[SOURCE]),
                                step("Gravity", search="completed", sources=[SOURCE]),
                                step("Gravity", search="in_progress", sources=[SOURCE]),
                                step("Gravity", sources=[SOURCE]), step("Gravity", search="completed"),
                                step("Gravity", search="completed", sources=[dict(SOURCE, url="https:///")]),
                                step("Gravity", search="completed", sources=[SOURCE]),
                                step("Draft with source", calls=[action("calculator", {"expression": "2+3"})],
                                     search="completed", sources=[SOURCE]), step("Result is 5."))
                self.assertEqual(self.chat()["sources"], [])
                citation = self.chat(search=True)["sources"][0]
                self.assertEqual(citation, dict(SOURCE, start=0, end=1) if provider == "openai"
                                 else dict(SOURCE, start=7, end=7))
                for _ in range(4):
                    self.chat(search=True, status=502)
                self.chat(status=502)
                self.assertEqual(self.chat(search=True)["sources"], [dict(SOURCE, start=12, end=12)])
                self.assertEqual(script.search_flags(), [False, True, True, True, True, True, False, True, False])
                self.assertFalse(script.pending)

    def test_v4_codex_over_budget_search_events_reject_before_dispatch_or_commit(self):
        branch = f"question-{uuid4().hex}"
        with ExitStack() as stack:
            script = Script(self.app, stack, "codex", step(calls=[action("calculator", {"expression": "2+3"})],
                                                            search="completed", search_count=7, sources=[SOURCE]))
            dispatch = stack.enter_context(patch.object(self.app.ai, "calculate", wraps=self.app.ai.calculate))
            with self.assertLogs(self.app.tutor_agent.log, "INFO") as logs:
                self.assertIn("limit", self.chat(branch=branch, search=True, status=502)["detail"])
            dispatch.assert_not_called()
            self.assertEqual(self.client.get(CHAT + branch).json(), [])
            self.assertEqual(script.search_flags(), [True])
            self.assertFalse(script.pending)
            self.assertTrue(any("reason=limit steps=1" in line for line in logs.output))

    def test_v5_deadline_budget_lease_and_retry(self):
        for provider in ("openai", "codex"):
            with self.subTest(provider=provider), ExitStack() as stack:
                script = Script(self.app, stack, provider, "timeout", step("Late reply"), step("Retry succeeded"),
                                step("Interrupted reply"), step("Second retry succeeded"))
                branch = f"question-{uuid4().hex}"
                request = str(uuid4())
                with self.assertLogs(self.app.tutor_agent.log, "INFO") as logs:
                    self.chat(branch=branch, request_id=request, status=504)
                self.assertTrue(any("reason=deadline" in line for line in logs.output))
                self.assertGreater(script.requests[0][1], 0)
                self.assertLessEqual(script.requests[0][1], 30)
                self.assertEqual(self.client.get(CHAT + branch).json(), [])
                clock = [0.0]
                with patch.object(self.app.tutor_agent, "monotonic", side_effect=lambda: clock[0]):
                    script.before_response = lambda: clock.__setitem__(0, 31.0)
                    self.chat(branch=branch, request_id=request, status=504)
                self.assertEqual(self.client.get(CHAT + branch).json(), [])
                script.before_response = None
                self.assertEqual(self.chat(branch=branch, request_id=request)["text"], "Retry succeeded")
                # Invalidate the reserved revision while the second provider reply is in flight.
                def interrupt():
                    with self.app.db() as conn:
                        conn.execute("UPDATE tutor_leases SET expires=0 WHERE branch=?",
                                     ("thread:physics:free-fall:" + branch,))

                request = str(uuid4())
                script.before_response = interrupt
                with self.assertLogs(self.app.tutor_agent.log, "INFO") as logs:
                    self.chat(branch=branch, request_id=request, status=409)
                self.assertTrue(any("reason=interrupted" in line for line in logs.output))
                self.assertEqual(len(self.client.get(CHAT + branch).json()), 2)
                script.before_response = None
                self.assertEqual(self.chat(branch=branch, request_id=request)["text"], "Second retry succeeded")
                with patch.dict(os.environ, {"STUDY_BOUNDED_CONTEXT": "1", "STUDY_TUTOR_CONTEXT_WINDOW": "6145"}):
                    self.chat(status=422)
                self.assertEqual(len(script.requests), 5)
                self.assertFalse(script.pending)

    def test_v5_summary_and_database_commit_share_deadline(self):
        for provider in ("openai", "codex"):
            with self.subTest(provider=provider), ExitStack() as stack:
                script = Script(self.app, stack, provider, step('{"text":"Earlier calculation recorded."}'),
                                step("Decision finished."), step("Expired during commit."),
                                step("Retried after deadline."))
                branch = f"question-{uuid4().hex}"
                history = [dict(role=role, text="Synthetic context " * 41)
                           for _ in range(14) for role in ("user", "assistant")]
                self.app.put("thread:physics:free-fall:" + branch, history)
                clock = [0.0]
                with patch.object(self.app.tutor_agent, "monotonic", side_effect=lambda: clock[0]), \
                        patch.dict(os.environ, {"STUDY_BOUNDED_CONTEXT": "1", "STUDY_TUTOR_CONTEXT_WINDOW": "15500"}):
                    script.before_response = lambda: clock.__setitem__(0, clock[0] + 2)
                    self.assertEqual(self.chat(branch=branch)["text"], "Decision finished.")
                summary, decision = script.requests
                request = summary[0]
                self.assertEqual(request["schema"] if provider == "codex" else request["text"]["format"]["name"],
                                 "Summary")
                self.assertEqual((summary[1], decision[1]), (30, 28))
                self.assertEqual(len(self.client.get(CHAT + branch).json()), len(history) + 2)

                branch = f"question-{uuid4().hex}"
                request_id = str(uuid4())
                commit = self.app.chat_state.Send.commit

                def delayed_commit(reservation, *args, **kwargs):
                    clock[0] += 31
                    return commit(reservation, *args, **kwargs)

                script.before_response = None
                with patch.object(self.app.tutor_agent, "monotonic", side_effect=lambda: clock[0]), \
                        patch.object(self.app.chat_state.Send, "commit", delayed_commit):
                    self.chat(branch=branch, request_id=request_id, status=504)
                self.assertEqual(self.client.get(CHAT + branch).json(), [])
                self.assertEqual(self.chat(branch=branch, request_id=request_id)["text"], "Retried after deadline.")
                self.assertFalse(script.pending)

    def test_v6_scoped_specialist_and_fallback(self):
        calc = action("calculator", {"expression": "0.5*9.81*2**2"})
        specialist = action("physics_explanation")
        for provider in ("openai", "codex"):
            with self.subTest(provider=provider), ExitStack() as stack:
                script = Script(self.app, stack, provider, step(calls=[calc]), step(calls=[specialist]),
                                step(json.dumps({"text": "From rest use s = at²/2."})),
                                step("The object moves 19.62 m."), step(calls=[specialist]), step("Please supply the data."),
                                step(calls=[calc]), step(calls=[specialist]), step('{"text":""}'),
                                step("Using the calculation directly, 19.62 m."))
                branch = f"question-{uuid4().hex}"
                self.chat(branch=branch, text="Explain the verified fall.")
                request = script.requests[2][0]
                if provider == "openai":
                    self.assertEqual(request["text"]["format"]["name"], "Recommendation")
                    self.assertNotIn("tools", request)
                    payload = json.loads(request["input"])
                else:
                    self.assertEqual((request["schema"], request["model"], request["search"]),
                                     ("Recommendation", "fixture-model", False))
                    payload = request["context"]
                self.assertEqual(set(payload), {"question", "lesson_excerpt", "verified_result"})
                self.assertEqual(payload["question"], "Explain the verified fall.")
                self.assertTrue(payload["lesson_excerpt"])
                self.assertEqual(payload["verified_result"]["output"], {"result": 19.62})
                self.assertIn("recommendation", script.observations()[1])
                self.chat()
                self.assertEqual(script.observations(), [{"error": "verified_result_required"}])
                self.chat()
                self.assertEqual(script.observations()[-1], {"error": "specialist_unavailable"})
                if provider == "openai":
                    batch = [action("calculator", {"expression": f"{i}+1"}) for i in range(6)]
                    script.pending.extend([step(calls=batch), step(calls=[specialist])])
                    self.chat(status=502)
                else:
                    # A charged search followed by five sequential tools consumes all six actions.
                    script.pending.extend([step(calls=[action("calculator", {"expression": f"{i}+1"})],
                                                search="completed" if i == 0 else None, sources=[SOURCE]) for i in range(5)])
                    script.pending.append(step(calls=[specialist]))
                    self.chat(search=True, status=502)
                self.assertFalse(script.pending)


if __name__ == "__main__":
    unittest.main()
