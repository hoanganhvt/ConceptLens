"""Measure chat-route overhead with zero-network OpenAI and Codex fixtures."""

import argparse
from contextlib import ExitStack
import json
import math
import os
from pathlib import Path
from statistics import median
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "tests/evals")]
from fixtures import answer, tool
from runner import openai_response


def run(data, samples):
    import httpx
    from fastapi.testclient import TestClient
    from openai import OpenAI

    os.environ.update(STUDY_DATA=data, STUDY_BOUNDED_CONTEXT="1", STUDY_TUTOR_CONTEXT_WINDOW="16384",
                      STUDY_TUTOR_MODEL_WINDOWS="{}", STUDY_TUTOR_DEADLINE_SECONDS="180")
    from backend import main

    script, wire_bytes, routing_modes = [], [], []

    def openai_stub(request):
        wire_bytes.append(len(request.content))
        routing_modes.append(any(tool.get("name") == "clarify" for tool in json.loads(request.content)["tools"]))
        return httpx.Response(200, json=openai_response(script.pop(0)))

    def codex_stub(args, **kwargs):
        if "login" in args:
            return subprocess.CompletedProcess(args, 0, b"", b"")
        schema = Path(args[args.index("--output-schema") + 1])
        schema_bytes = schema.read_bytes()
        routing_modes.append(json.loads(schema_bytes)["title"] == "AgentStep")
        wire_bytes.append(len(kwargs["input"].encode()) + len(schema_bytes))
        step = dict(script.pop(0))
        step["arguments_json"] = json.dumps(step.pop("arguments"))
        event = {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(step)}}
        return subprocess.CompletedProcess(args, 0, json.dumps(event), "")

    output = []
    with ExitStack() as stack:
        client = stack.enter_context(TestClient(main.app))
        transport = stack.enter_context(httpx.Client(transport=httpx.MockTransport(openai_stub), trust_env=False))
        sdk = OpenAI(api_key="synthetic", http_client=transport)
        stack.enter_context(patch.object(main.ai, "client", return_value=sdk))
        stack.enter_context(patch.object(main.providers.shutil, "which", return_value="scripted-codex"))
        stack.enter_context(patch.object(main.providers.subprocess, "run", side_effect=codex_stub))
        stack.enter_context(patch.object(main, "ai_settings"))
        for provider in ("openai", "codex"):
            main.ai_settings.return_value = {"provider": provider, "codex_model": "scripted"}
            for phase4 in (False, True):
                os.environ["STUDY_TUTOR_AGENT"] = str(int(phase4))
                for case, question, steps in (
                    ("answer", "What is acceleration?", [answer("Acceleration is change in velocity per second.")]),
                    ("calculation", "Convert 1962 cm to metres.",
                     [tool("calculator", expression="1962/100"), answer("19.62 m")]),
                ):
                    for index in range(samples + 3):
                        script[:] = steps
                        wire_bytes.clear()
                        routing_modes.clear()
                        branch = f"question-{uuid4().hex}"
                        start = perf_counter()
                        result = client.post(f"/api/chat/physics/free-fall/{branch}",
                                             json={"text": question})
                        elapsed = (perf_counter() - start) * 1000
                        assert result.status_code == 200, result.text
                        reply = result.json()[-1]
                        assert not script and len(wire_bytes) == len(steps)
                        assert routing_modes == [phase4] * len(steps)
                        assert reply["text"] == steps[-1]["text"]
                        if case == "calculation":
                            assert reply["traces"][0]["output"]["result"] == 19.62
                        else:
                            assert not reply["traces"]
                        if index >= 3:
                            output.append(dict(provider=provider, phase4=phase4, case=case,
                                               elapsed_ms=round(elapsed, 3), request_bytes=list(wire_bytes)))
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=20)
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("--samples must be positive")
    with TemporaryDirectory(prefix="conceptlens-phase4-") as data:
        rows = run(data, args.samples)
    args.output.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    for provider in ("openai", "codex"):
        for phase4 in (False, True):
            for case in ("answer", "calculation"):
                group = [row for row in rows if (row["provider"], row["phase4"], row["case"]) == (provider, phase4, case)]
                times = sorted(row["elapsed_ms"] for row in group)
                print(f"{provider} phase4={phase4} {case}: n={len(times)} p50={median(times):.3f} ms "
                      f"p95={times[math.ceil(len(times) * .95) - 1]:.3f} ms "
                      f"mean_input_bytes={sum(sum(row['request_bytes']) for row in group) / len(times):.0f}")


if __name__ == "__main__":
    main()
