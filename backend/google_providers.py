from contextlib import nullcontext
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from fastapi import HTTPException

from . import providers
from .language import tr
from .prompt_files import prompt


GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/"
AGY_PERMISSIONS = {
    "agentMode": "", "toolPermission": "strict", "allowNonWorkspaceAccess": False,
    "permissions": {"allow": [], "deny": [f"{tool}(*)" for tool in
                    ("read_file", "write_file", "read_url", "execute_url", "command", "unsandboxed", "mcp")]},
}


def require_web_provider():
    raise HTTPException(422, tr("Để tra cứu web, hãy chọn OpenAI hoặc Codex CLI trong Cài đặt.",
                                "Choose OpenAI or Codex CLI in Settings to search the web."))


def gemini_request(path, settings, timeout, payload=None):
    key = providers.api_key(settings, google=True)
    if not key:
        raise HTTPException(503, tr("Nhập Gemini API key trong Cài đặt hoặc đặt GEMINI_API_KEY.",
                                   "Enter a Gemini API key in Settings or set GEMINI_API_KEY."))
    data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    request = Request(GEMINI_URL + path, data=data, headers={"Content-Type": "application/json"})
    request.add_unredirected_header("x-goog-api-key", key)
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as exc:
        status = 429 if exc.code == 429 else 502
        raise HTTPException(status, tr("Gemini API từ chối yêu cầu. Kiểm tra API key, model và hạn mức.",
                                      "Gemini API rejected the request. Check the API key, model and quota.")) from exc
    except (URLError, TimeoutError) as exc:
        if isinstance(exc, TimeoutError) or isinstance(getattr(exc, "reason", None), TimeoutError):
            raise HTTPException(504, tr("Gemini API trả lời quá chậm.", "Gemini API timed out.")) from exc
        raise HTTPException(502, tr("Không kết nối được Gemini API.", "Could not connect to Gemini API.")) from exc
    except ValueError as exc:
        raise HTTPException(502, tr("Gemini API trả về phản hồi không hợp lệ.", "Gemini API returned an invalid response.")) from exc


def request_for(schema, instructions, context, provider):
    if provider == "agy":
        return providers.codex_request(schema, instructions, context)
    return {
        "systemInstruction": {"parts": [{"text": instructions + "\n\n" + prompt("providers/codex-context")}]},
        "contents": [{"parts": [{"text": providers.codex_context(context)}]}],
        "generationConfig": {"responseMimeType": "application/json", "responseJsonSchema": schema.model_json_schema()},
    }


def request_size(request):
    parts = request if isinstance(request, tuple) else (json.dumps(request, ensure_ascii=False),)
    return sum(len(part.encode()) for part in parts)


def agy_command(arguments, *, timeout, folder, stdin=None):
    executable = shutil.which("agy")
    if not executable:
        raise HTTPException(503, tr("Không tìm thấy lệnh agy trong PATH của máy chủ.",
                                   "The agy command was not found on the server PATH."))
    try:
        return subprocess.run([executable, *arguments], input=stdin, encoding="utf-8", errors="replace",
                              capture_output=True, cwd=folder, timeout=timeout, env=providers.cli_environment(),
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(504, tr("Antigravity CLI trả lời quá chậm.", "Antigravity CLI timed out.")) from exc
    except OSError as exc:
        raise HTTPException(503, tr("Không khởi chạy được agy.", "Could not start agy.")) from exc


def agy_result(request, model, timeout):
    schema_text, instructions = request
    with TemporaryDirectory(prefix="study-agy-") as folder:
        schema_path = Path(folder) / "schema.json"
        schema_path.write_text(schema_text, encoding="utf-8")
        args = ["--input-format", "stream-json", "--output-format", "stream-json", "--json-schema", str(schema_path),
                "--disable-slash-commands", "--sandbox", "--settings", json.dumps(AGY_PERMISSIONS),
                "--log-file", str(Path(folder) / "agy.log"), "--print-timeout", f"{timeout:.3f}s"]
        if model:
            args.extend(["--model", model])
        event = {"event": "user", "message": {"content": instructions}}
        result = agy_command(args, timeout=timeout, folder=folder, stdin=json.dumps(event, ensure_ascii=False) + "\n")
    if result.returncode:
        raise HTTPException(502, tr("agy không hoàn thành. Chạy agy trong terminal để kiểm tra đăng nhập và model.",
                                    "agy did not complete. Run agy in a terminal to check sign-in and model selection."))
    events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    [envelope] = [event["result"] for event in events if event.get("event") == "result"]
    if envelope["status"] != "SUCCESS":
        raise HTTPException(502, tr("agy không hoàn thành. Kiểm tra đăng nhập và model trong terminal.",
                                    "agy did not complete. Check sign-in and model selection in a terminal."))
    return envelope["structured_output"], envelope.get("usage") or {}


def result(schema, instructions, context, search=False, *, settings, model=None, budget=None, renew=None,
           kind="tutor", pre_send=None, remaining=None):
    if search:
        require_web_provider()
    provider = settings["provider"]
    request = request_for(schema, instructions, context, provider)
    measurement = budget.measure(request_size(request), kind) if budget else nullcontext({})
    with measurement as usage:
        if renew:
            renew()
        if pre_send:
            pre_send()
        timeout = remaining() if remaining else 180
        try:
            if provider == "agy":
                value, reported = agy_result(request, model, timeout)
                parsed = schema.model_validate(value)
                tokens = (reported.get("input_tokens"), reported.get("output_tokens"))
            else:
                response = gemini_request(f"models/{quote(model, safe='')}:generateContent", settings, timeout, request)
                candidate = response["candidates"][0]
                if candidate.get("finishReason") != "STOP":
                    raise ValueError("Incomplete Gemini response")
                parts = candidate["content"]["parts"]
                parsed = schema.model_validate_json("".join(part.get("text", "") for part in parts if not part.get("thought")))
                reported = response.get("usageMetadata", {})
                tokens = (reported.get("promptTokenCount"), reported.get("candidatesTokenCount"))
            if remaining:
                remaining()
            usage.update(input_tokens=tokens[0], output_tokens=tokens[1])
            return parsed.model_dump()
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise HTTPException(502, tr("Model Google chưa trả về nội dung hợp lệ. Hãy thử lại.",
                                        "The Google model returned invalid content. Please try again.")) from exc


def model_catalog(provider, settings):
    if provider == "gemini":
        response = gemini_request("models?pageSize=1000", settings, 10)
        return [{"id": model["name"].removeprefix("models/"), "name": model.get("displayName") or model["name"]}
                for model in response.get("models", [])
                if "generateContent" in model.get("supportedGenerationMethods", []) and
                model["name"].startswith("models/gemini-") and
                not re.search(r"-(?:image|tts|audio|live|embedding)(?:-|$)", model["name"])]
    with TemporaryDirectory(prefix="study-agy-models-") as folder:
        models = agy_command(["models"], timeout=10, folder=folder)
    matches = re.findall(r"^(gemini-[\w.-]+)[ \t]+([^\r\n]+)", models.stdout, re.MULTILINE)
    if models.returncode or not matches:
        raise HTTPException(502, tr("Chưa lấy được model. Mở agy trong terminal để đăng nhập Google.",
                                    "Could not list models. Open agy in a terminal to sign in to Google."))
    return [{"id": slug, "name": name.strip()} for slug, name in matches]
