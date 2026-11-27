from contextlib import nullcontext
import json
import os
from pathlib import Path
from queue import Empty, SimpleQueue
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory
from threading import Lock, Thread
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from fastapi import HTTPException

from . import providers
from .language import tr
from .models import LessonDraft
from .prompt_files import prompt


GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/"
AGY_LESSON_TIMEOUT = 360
AGY_OUTPUT_LIMIT = 1_048_576
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


class AgyOutputLimit(ValueError):
    pass


def run_agy_process(args, *, input, cwd, timeout, env):
    deadline = monotonic() + timeout
    input_bytes = input.encode("utf-8") if input is not None else None
    completed = SimpleQueue()
    lock = Lock()
    stdout = bytearray()
    stderr = bytearray()

    def read(pipe, buffer):
        try:
            while data := pipe.read(65536):
                with lock:
                    if len(stdout) + len(stderr) + len(data) > AGY_OUTPUT_LIMIT:
                        raise AgyOutputLimit()
                    buffer.extend(data)
        except (OSError, ValueError) as exc:
            completed.put(exc)
        else:
            completed.put(None)

    def write(pipe):
        try:
            with pipe:
                data = memoryview(input_bytes)
                while data:
                    written = pipe.write(data)
                    if not written:
                        raise OSError("Could not write to agy")
                    data = data[written:]
        except BrokenPipeError:
            completed.put(None)
        except (OSError, ValueError) as exc:
            completed.put(exc)
        else:
            completed.put(None)

    with subprocess.Popen(args, stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0, cwd=cwd, env=env,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) as process:
        workers = [Thread(target=read, args=(process.stdout, stdout), daemon=True),
                   Thread(target=read, args=(process.stderr, stderr), daemon=True)]
        if input is not None:
            workers.append(Thread(target=write, args=(process.stdin,), daemon=True))
        try:
            for worker in workers:
                worker.start()
            for _ in workers:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(args, timeout)
                try:
                    error = completed.get(timeout=remaining)
                except Empty as exc:
                    raise subprocess.TimeoutExpired(args, timeout) from exc
                if error:
                    raise error
            returncode = process.wait(timeout=max(0, deadline - monotonic()))
        except BaseException:
            process.kill()
            raise
    return subprocess.CompletedProcess(args, returncode, stdout.decode("utf-8", errors="replace"),
                                       stderr.decode("utf-8", errors="replace"))


def agy_command(arguments, *, timeout, folder, stdin=None):
    executable = shutil.which("agy")
    if not executable:
        raise HTTPException(503, tr("Không tìm thấy lệnh agy trong PATH của máy chủ.",
                                   "The agy command was not found on the server PATH."))
    try:
        return run_agy_process([executable, *arguments], input=stdin, cwd=folder, timeout=timeout,
                               env=providers.cli_environment())
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(504, tr("Antigravity CLI trả lời quá chậm.", "Antigravity CLI timed out.")) from exc
    except OSError as exc:
        raise HTTPException(503, tr("Không khởi chạy được agy.", "Could not start agy.")) from exc
    except AgyOutputLimit as exc:
        raise HTTPException(502, tr("Phản hồi của agy vượt giới hạn.", "agy returned too much output.")) from exc


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
    if any(line.startswith("[agy] print timeout after ") for line in result.stderr.splitlines()):
        raise HTTPException(504, tr("Antigravity CLI trả lời quá chậm.", "Antigravity CLI timed out."))
    if result.returncode:
        raise HTTPException(502, tr("agy không hoàn thành. Chạy agy trong terminal để kiểm tra đăng nhập và model.",
                                    "agy did not complete. Run agy in a terminal to check sign-in and model selection."))
    events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    [envelope] = [event["result"] for event in events if event.get("event") == "result"]
    if envelope.get("finished_reason") == "print_timeout":
        raise HTTPException(504, tr("Antigravity CLI trả lời quá chậm.", "Antigravity CLI timed out."))
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
        if remaining is None and provider == "agy" and schema is LessonDraft:
            timeout = AGY_LESSON_TIMEOUT
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
    if models.returncode:
        raise HTTPException(502, tr("Chưa lấy được model. Mở agy trong terminal để đăng nhập Google.",
                                    "Could not list models. Open agy in a terminal to sign in to Google."))
    try:
        entries = []
        for line in models.stdout.splitlines():
            line = line.strip()
            if not line or line.lower() in {"available models:", "models:"} or re.fullmatch(r"[- \t]+", line):
                continue
            match = re.fullmatch(r"(\S+)(?: {2,}|\t+)(.+)", line)
            if not match:
                raise ValueError("Malformed model row")
            slug, name = match.groups()
            if slug.lower() in {"model", "slug", "id", "model_id"} and name.strip().lower() in {
                "name", "display name", "model name", "description"
            }:
                continue
            entries.append((slug, name))
        options = providers.catalog_options(entries)
    except ValueError as exc:
        raise HTTPException(502, tr("agy không trả về danh sách model hợp lệ.",
                                    "agy did not return a valid model catalog.")) from exc
    if not options:
        raise HTTPException(502, tr("agy không trả về model nào.", "agy returned no models."))
    return options
