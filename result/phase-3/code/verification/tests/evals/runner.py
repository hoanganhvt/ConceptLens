"""Replay the current tutor through the reader's HTTP API."""

import argparse
from collections import deque
from contextlib import ExitStack
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

from fixtures import CASES, LIVE_CASES, OTHER, exercise, exercise_bounded, seed, unrelated_content


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
STUB = {"openai": "scripted-openai-http-v1", "codex": "scripted-codex-jsonl-v1"}
BOUNDED_WINDOW = 11000
BOUNDED_LIMIT = BOUNDED_WINDOW - 4096 - 2048


def encode(value):
    return json.dumps(value, ensure_ascii=False, default=lambda item: item.model_dump(mode="json"))


def digest(data):
    return sha256(data).hexdigest()


def milliseconds(start):
    return round((perf_counter() - start) * 1000, 3)


def openai_response(step):
    if step["action"] != "answer":
        output = [{"type": "function_call", "id": "fc_eval", "call_id": "call_eval", "status": "completed",
                   "name": step["action"], "arguments": encode(step["arguments"])}]
    else:
        output = [{"type": "web_search_call", "id": "ws_eval", "status": "completed"}] if step["sources"] else []
        annotations = [dict(source, type="url_citation", start_index=0, end_index=len(step["text"]))
                       for source in step["sources"]]
        output.append({"type": "message", "id": "msg_eval", "status": "completed", "role": "assistant",
                       "content": [{"type": "output_text", "text": step["text"], "annotations": annotations}]})
    return {"id": "resp_eval", "object": "response", "status": "completed", "output": output}


class Route:
    def __init__(self, client, language):
        self.client = client
        self.language = language

    def request(self, method, path, body):
        return self.client.request(method, f"/api/{path}", json=body, headers={"X-Study-Language": self.language})

    def __call__(self, method, path, **body):
        response = self.request(method, path, body or None)
        assert response.status_code == 200, (method, path, response.status_code, response.text)
        return response.json()


class Recorder:
    def __init__(self, route, live, codex_model, bounded):
        self.route = route
        self.live = live
        self.codex_model = codex_model
        self.bounded = bounded
        self.available = True
        self.script = deque()
        self.calls = []
        self.turns = []

    def record(self, provider, boundary_input, invoke, usage_from, *, request_bytes=None, kind="tutor"):
        serialized = encode(boundary_input)
        size = len(serialized.encode("utf-8")) if request_bytes is None else request_bytes
        entry = {"provider": provider, "input": json.loads(serialized), "request_bytes": size,
                 "status": "error", "usage": None, "kind": kind}
        self.calls.append(entry)
        start = perf_counter()
        try:
            response = invoke()
            entry["status"], entry["usage"] = usage_from(response)
            return response
        finally:
            entry["elapsed_ms"] = milliseconds(start)

    def select(self, provider):
        self.provider = provider
        self.route("POST", "settings", provider=provider, codex_model=self.codex_model)

    def __call__(self, branch, question, steps, *, search=False, expected=200):
        self.script = deque(steps)
        first_call = len(self.calls)
        start = perf_counter()
        response = self.route.request("POST", branch, {"text": question, "search": search})
        elapsed = milliseconds(start)
        public = response.json()
        if not self.live:
            assert response.status_code == expected, (response.status_code, public)
            assert not self.script, "The adapter did not consume the scripted responses."
        turn = {"provider": self.provider, "search_requested": search, "status": response.status_code,
                "elapsed_ms": elapsed, "reply": public[-1] if response.status_code == 200 else public,
                "calls": self.calls[first_call:]}
        self.turns.append(turn)
        return turn

    def install(self, stack, backend):
        import httpx

        ai, providers = backend.ai, backend.providers
        original_client = ai.client
        original_run = providers.subprocess.run

        def sdk_stub(request):
            assert request.url.path.endswith("/responses"), request.url.path
            if self.bounded:
                assert len(request.content) <= BOUNDED_LIMIT, len(request.content)
                self.calls[-1]["request_bytes"] = len(request.content)
                if self.calls[-1]["kind"] == "summary":
                    return httpx.Response(200, json=openai_response(self.compaction(json.loads(request.content)["input"])))
            return httpx.Response(200, json=openai_response(self.script.popleft()))

        if not self.live:
            stack.enter_context(patch.object(providers, "api_key",
                                             side_effect=lambda _: "synthetic" if self.available else None))
            stack.enter_context(patch.object(providers, "cli_status",
                                             side_effect=lambda _: "ready" if self.available else "missing"))
            stack.enter_context(patch.object(providers, "codex_models", return_value=[]))
            original_which = providers.shutil.which

            def find(executable, *args, **kwargs):
                if executable == "codex":
                    return "scripted-codex" if self.available else None
                return original_which(executable, *args, **kwargs)

            stack.enter_context(patch.object(providers.shutil, "which", side_effect=find))
            transport = stack.enter_context(httpx.Client(transport=httpx.MockTransport(sdk_stub), trust_env=False))
            original_constructor = ai.OpenAI
            stack.enter_context(patch.object(ai, "OpenAI",
                                             side_effect=lambda **kw: original_constructor(http_client=transport, **kw)))

        def openai_client(settings):
            client = stack.enter_context(original_client(settings))
            create = client.responses.create

            def invoke(**request):
                boundary_input = dict(request)
                summary = "text" in request
                boundary_input["prefix" if summary else "messages"] = boundary_input.pop("input")

                def usage(response):
                    counts = response.usage
                    return "ok", ({"input_tokens": counts.input_tokens, "output_tokens": counts.output_tokens}
                                  if counts else None)

                return self.record("openai", boundary_input, lambda: create(**request), usage,
                                   kind="summary" if summary else "tutor")

            client.responses.create = invoke
            return client

        def codex_process(args, **kwargs):
            if "--output-schema" not in args:
                assert self.live, "Unexpected subprocess in deterministic replay."
                return original_run(args, **kwargs)
            stdin = kwargs["input"]
            instructions, context = stdin.rsplit("\n", 1)
            search = next(flag.split('"')[1] for flag in args if flag.startswith("web_search="))
            schema = Path(args[args.index("--output-schema") + 1]).read_bytes()
            boundary_input = {"stdin": stdin, "instructions": instructions, "context": json.loads(context),
                              "schema": json.loads(schema),
                              "search": search}
            boundary_input["model"] = args[args.index("--model") + 1] if "--model" in args else None
            size = len(stdin.encode("utf-8")) + len(schema)
            summary = boundary_input["schema"].get("title") == "Summary"
            if self.bounded:
                assert size <= BOUNDED_LIMIT, size

            def invoke():
                if self.live:
                    return original_run(args, **kwargs)
                if summary:
                    message = json.loads(self.compaction(context)["text"])
                else:
                    step = self.script.popleft()
                    message = dict(step, arguments_json=encode(step["arguments"]))
                    del message["arguments"]
                items = [{"type": "web_search", "query": "free fall"}] if search == "live" else []
                items.append({"type": "agent_message", "text": encode(message)})
                stdout = "\n".join(encode({"type": "item.completed", "item": item}) for item in items)
                return subprocess.CompletedProcess(args, 0, stdout, "")

            def usage(response):
                if response.returncode:
                    return "error", None
                for line in reversed(response.stdout.splitlines()):
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if event.get("type") == "turn.completed" and event.get("usage"):
                        return "ok", {key: event["usage"][key] for key in ("input_tokens", "output_tokens")
                                      if key in event["usage"]}
                return "ok", None

            return self.record("codex", boundary_input, invoke, usage,
                               request_bytes=size, kind="summary" if summary else "tutor")

        stack.enter_context(patch.object(ai, "client", side_effect=openai_client))
        stack.enter_context(patch.object(providers.subprocess, "run", side_effect=codex_process))

    def compaction(self, prefix):
        from fixtures import answer

        prefix = json.loads(prefix) if isinstance(prefix, str) else prefix
        assert prefix["turns"][0]["through"] > prefix["covered_through"]
        previous = (prefix["previous"] or {}).get("text", "")
        turns = encode(prefix["turns"])
        if "fall direction" in turns:
            previous = "The learner chose downward as positive for the original fall direction."
        elif "chiều dương hướng xuống" in turns:
            previous = "Người học chọn chiều dương hướng xuống cho lần rơi ban đầu."
        fallback = "The learner reviewed the free-fall model." if self.route.language == "en" else "Người học ôn lại sự rơi tự do."
        return answer(encode({"text": previous or fallback}))

    def report(self, case, initial_provider, openai_model):
        evidence = []
        metrics = []
        for turn in self.turns:
            evidence.append({"reply": turn["reply"], "diagnostic_status": turn["status"]})
            call_metrics = []
            for call in turn["calls"]:
                fields = ("provider", "status", "request_bytes", "elapsed_ms", "usage", "kind")
                call_metrics.append({field: call[field] for field in fields})
                if not self.live:
                    evidence[-1].setdefault("provider_inputs", []).append(call["input"])
            metrics.append({key: turn[key] for key in ("provider", "search_requested", "status", "elapsed_ms")}
                           | {"calls": call_metrics})
        providers = {turn["provider"] for turn in self.turns}
        models = {"openai": openai_model, "codex": self.codex_model} if self.live else STUB
        return {"case": case, "language": self.route.language, "initial_provider": initial_provider,
                "models_or_stubs": {provider: models[provider] for provider in sorted(providers)},
                "turns": metrics, "evidence": evidence}


def run_case(case, provider, language, live, codex_model, bounded):
    with TemporaryDirectory(prefix="conceptlens-eval-") as study_data:
        os.environ["STUDY_DATA"] = study_data
        os.environ["STUDY_BOUNDED_CONTEXT"] = "1" if bounded else "0"
        if bounded:
            os.environ["STUDY_TUTOR_CONTEXT_WINDOW"] = str(BOUNDED_WINDOW)
            os.environ["STUDY_TUTOR_MODEL_WINDOWS"] = "{}"
        sys.path.insert(0, str(ROOT))
        from fastapi.testclient import TestClient
        from backend import main as backend

        with ExitStack() as stack:
            route = Route(stack.enter_context(TestClient(backend.app)), language)
            recorder = Recorder(route, live, codex_model, bounded)
            recorder.install(stack, backend)
            recorder.select(provider)
            fixtures = unrelated_content(backend.Roadmap, backend.Lesson)
            with patch.object(backend.ai, "structured", side_effect=lambda schema, *args, **kw: fixtures[schema]):
                seeded = seed(route, fixtures[backend.Lesson])
            if bounded:
                exercise_bounded(route, recorder, *seeded)
            else:
                exercise(route, recorder, case, provider, live, *seeded)
            return recorder.report(case, provider, backend.ai.MODEL)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Use real providers with synthetic study data.")
    parser.add_argument("--bounded", action="store_true", help="Replay Phase 1 using a small context window.")
    parser.add_argument("--provider", choices=[*OTHER, "both"], default="both")
    parser.add_argument("--codex-model", help="Explicit Codex model ID for reproducible live runs.")
    parser.add_argument("--output", type=Path, required=True, help="Directory for JSON metrics and evidence.")
    parser.add_argument("--worker", nargs=3, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not __debug__:
        parser.error("Run without Python optimization to enable replay assertions.")
    if args.live and args.bounded:
        parser.error("The bounded fixture uses scripted providers.")
    if args.worker:
        result = run_case(*args.worker, args.live, args.codex_model or (None if args.live else STUB["codex"]),
                          args.bounded)
        print(json.dumps(result))
        return 0

    providers = tuple(OTHER) if args.provider == "both" else (args.provider,)
    if args.live and "codex" in providers and not args.codex_model:
        parser.error("Live Codex evaluation requires --codex-model.")
    if args.live and "openai" in providers and not os.getenv("OPENAI_API_KEY"):
        parser.error("Live OpenAI evaluation requires OPENAI_API_KEY in the environment.")

    reports = []
    mode = "live" if args.live else "bounded" if args.bounded else "replay"
    cases = ("bounded-long",) if args.bounded else LIVE_CASES if args.live else CASES
    for provider in providers:
        for language in ("en", "vi"):
            for case in cases:
                command = [sys.executable, "-E", str(HERE / "runner.py"), "--output", str(args.output),
                           "--worker", case, provider, language]
                if args.live:
                    command.append("--live")
                if args.bounded:
                    command.append("--bounded")
                if args.codex_model:
                    command.extend(["--codex-model", args.codex_model])
                result = subprocess.run(command, cwd=ROOT, capture_output=True, encoding="utf-8")
                if result.returncode:
                    print(f"Worker failed for {provider}/{language}/{case}.", file=sys.stderr)
                    if not args.live:
                        print(result.stderr, file=sys.stderr, end="")
                    return 1
                reports.append(json.loads(result.stdout))

    metadata = {
        "mode": mode,
        "input_limit": BOUNDED_LIMIT if args.bounded else None,
        "fixture_revision": digest((HERE / "fixtures.py").read_bytes()),
        "harness_revision": digest((HERE / "runner.py").read_bytes()),
        "prompt_file_sha256": {path.relative_to(ROOT).as_posix(): digest(path.read_bytes())
                               for path in sorted((ROOT / "prompts").rglob("*.md"))},
        "measurement": {
            "turn_ms": "Monotonic time around the in-process chat POST. Setup and worker startup are excluded.",
            "call_ms": "Monotonic time in SDK create or Codex exec. CLI discovery and JSONL parsing are excluded.",
            "request_bytes": "OpenAI HTTP body for bounded replay, recorded SDK arguments otherwise. "
                             "Codex measures stdin and output schema.",
            "usage": "Input and output token counts reported by the provider. Null means unavailable.",
        },
    }
    args.output.mkdir(parents=True, exist_ok=True)
    evidence = []
    for report in reports:
        evidence.append({key: report[key] for key in ("case", "language", "initial_provider", "models_or_stubs")}
                        | {"turns": report.pop("evidence")})
    for name, cases in (("metrics", reports), ("evidence", evidence)):
        (args.output / f"{mode}-{name}.json").write_text(
            json.dumps(dict(metadata, cases=cases), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    failures = sum(turn["status"] != 200 for report in reports for turn in report["turns"]) if args.live else 0
    print(f"{mode.capitalize()} completed: {len(reports)} cases, {failures} unexpected HTTP failures.")
    return int(failures > 0)


if __name__ == "__main__":
    raise SystemExit(main())
