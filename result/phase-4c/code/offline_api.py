"""Serve real FastAPI request fixtures over stdio without network access."""

import io
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from backend import main as app  # noqa: E402
from backend.demo import ROAD_EN, SAMPLE_EN  # noqa: E402
from backend.models import IllustrationBatch, LessonDraft, Roadmap  # noqa: E402


MODEL_NAMES = [("agy-alpha", "Fast Antigravity"), ("agy-beta", "Precise Antigravity")]
CODEX_NAMES = [("codex-alpha", "Fast Codex"), ("codex-beta", "Precise Codex")]
CATALOG = {"codex": "normal", "agy": "normal"}
CALLS = []
FAIL = {"prose": False, "scene": True, "repair": True}


def fixture_lesson():
    draft = deepcopy(SAMPLE_EN)
    scene, = draft.pop("illustrations")
    draft["illustration_plan"] = [
        {"section": 0, "brief": "scene-a"},
        {"section": 1, "brief": "scene-b"},
        {"section": 0, "brief": "scene-c"},
    ]
    return draft, scene


class ProtocolInput(io.StringIO):
    def close(self):
        self.trace = [json.loads(row) for row in self.getvalue().splitlines()]
        super().close()


class CodexProcess:
    def __init__(self, args, **kwargs):
        assert args[1:] == ["app-server", "--listen", "stdio://"]
        self.stdin = ProtocolInput()
        self.stdout = io.StringIO()
        mode = CATALOG["codex"]
        options = [] if mode == "empty" else [
            {"model": model, "displayName": name, "hidden": False} for model, name in CODEX_NAMES
        ]
        if mode == "malformed":
            options.append({"model": 42, "displayName": "invalid"})
        reply = {"id": 1, "result": {"data": options, "nextCursor": None}}
        if mode == "failure":
            reply = {"id": 1, "error": {"code": -32603}}
        for item in ({"id": 0, "result": {}}, reply):
            self.stdout.write(json.dumps(item) + "\n")
        self.stdout.seek(0)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        assert [row["method"] for row in self.stdin.trace] == ["initialize", "initialized", "model/list"]
        CALLS.append({"stage": "catalog", "provider": "codex"})

    def wait(self, timeout):
        return 0


def fake_agy(args, *, timeout, folder, stdin=None):
    if args == ["models"]:
        CALLS.append({"stage": "catalog", "provider": "agy"})
        options = MODEL_NAMES
        mode = CATALOG["agy"]
        if mode == "timeout":
            raise HTTPException(504, app.tr("Tải model agy hết thời gian.", "agy model catalog timed out."))
        if mode == "failure":
            return subprocess.CompletedProcess(args, 1, "", "Please sign in")
        if mode == "empty":
            options = []
        if mode == "removed":
            options = options[:1]
        if mode == "malformed":
            return subprocess.CompletedProcess(args, 0, "id name\n!invalid  Invalid", "")
        return subprocess.CompletedProcess(args, 0, "\n".join(f"{i}  {name}" for i, name in options), "")
    assert "--sandbox" in args and "--disable-slash-commands" in args
    assert "--settings" in args and "--json-schema" in args
    schema = json.loads(Path(args[args.index("--json-schema") + 1]).read_text(encoding="utf-8"))
    payload = json.loads(stdin)["message"]["content"]
    context = json.loads(payload.splitlines()[-1])
    model = args[args.index("--model") + 1]
    _, visual = fixture_lesson()
    if "illustrations" in schema["properties"]:
        brief, = context["illustration_plan"]
        assert "section" in context and "quiz" not in context and "sections" not in context
        CALLS.append({"stage": "scene", "provider": "agy", "model": model, "brief": brief["brief"]})
        if brief["brief"] == "scene-b" and FAIL["scene"]:
            return subprocess.CompletedProcess(args, 1, "", "[agy] print timeout after test timer")
        visual.update(title={"scene-a": "Scene A", "scene-b": "Scene B", "scene-c": "Scene C"}[brief["brief"]],
                      section=brief["section"])
        output = {"illustrations": [visual]}
    else:
        assert set(context) == {"item", "error"}
        assert "intro" not in context
        CALLS.append({"stage": "repair", "provider": "agy", "model": model})
        if FAIL["repair"]:
            visual["js"] = ""
        else:
            visual["css"] = "svg { width: 99%; }"
        output = visual
    frame = {"event": "result", "result": {"status": "SUCCESS", "structured_output": output}}
    return subprocess.CompletedProcess(args, 0, json.dumps(frame), "")


def fake_codex(schema, instructions, context, *, model=None, **kwargs):
    draft, scene = fixture_lesson()
    if schema is LessonDraft:
        assert set(context) == {"road", "topic"}
        CALLS.append({"stage": "prose", "provider": "codex", "model": model})
        if FAIL["prose"]:
            raise HTTPException(504, app.tr("Codex hết thời gian.", "Codex timed out."))
        return draft
    if schema is IllustrationBatch:
        brief, = context["illustration_plan"]
        CALLS.append({"stage": "scene", "provider": "codex", "model": model, "brief": brief["brief"]})
        return {"illustrations": [{**scene, "section": brief["section"]}]}
    raise AssertionError(f"unexpected schema {schema}")


def request(client, packet):
    response = client.request(packet["method"], packet["path"],
                              headers=packet.get("headers"), json=packet.get("body"))
    return {"status": response.status_code, "json": response.json()}


def command(client, packet):
    op = packet.get("op")
    if op == "request":
        return request(client, packet)
    if op == "parallel":
        with ThreadPoolExecutor(2) as pool:
            return list(pool.map(lambda item: request(client, item), packet["requests"]))
    if op == "catalog":
        CATALOG[packet["provider"]] = packet["mode"]
    elif op == "fail":
        FAIL[packet["stage"]] = packet["enabled"]
    elif op == "calls":
        return CALLS
    elif op == "seed":
        road = app.commit(Roadmap.model_validate({**ROAD_EN, "title": "Phase 4C synthetic course"}))
        return road
    elif op == "seed-legacy":
        key = "lesson:physics:free-fall"
        doc = app.get(key)
        doc["quiz"].append({"kind": "number", "prompt": "What is the second distance?", "choices": [],
                            "answer": "42 m", "explanation": "42 metres."})
        app.put(key, doc)
    else:
        raise AssertionError(f"unknown command {op}")
    return True


if __name__ == "__main__":
    stage_log = logging.getLogger("uvicorn.error.lessons")
    stage_log.setLevel(logging.INFO)
    stage_log.addHandler(logging.StreamHandler())
    with ExitStack() as stack:
        stack.enter_context(patch.object(app.providers, "cli_status", return_value="ready"))
        stack.enter_context(patch.object(app.providers, "codex_models", return_value=[]))
        stack.enter_context(patch.object(app.providers.shutil, "which", side_effect=lambda name: name))
        stack.enter_context(patch.object(app.providers.subprocess, "Popen", CodexProcess))
        stack.enter_context(patch.object(app.providers, "codex_result", side_effect=fake_codex))
        stack.enter_context(patch.object(app.google_providers, "agy_command", side_effect=fake_agy))
        client = stack.enter_context(TestClient(app.app))
        for line in sys.stdin:
            packet = json.loads(line)
            data = command(client, packet)
            print(json.dumps({"id": packet["id"], "data": data}), flush=True)
