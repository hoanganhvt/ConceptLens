from contextlib import nullcontext

from .language import tr
import base64
import ctypes
import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Annotated, Literal
from .prompt_files import prompt

from fastapi import HTTPException
from pydantic import BaseModel, Field, SecretStr, ValidationError
from openai.lib._pydantic import to_strict_json_schema


log = logging.getLogger("uvicorn.error").getChild("providers")
Provider = Literal["openai", "codex", "gemini", "agy"]
GoogleModel = Annotated[str, Field(max_length=128, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")]


class SettingsUpdate(BaseModel):
    provider: Provider
    visual_provider: Provider | None = None
    codex_model: str | None = Field(default=None, max_length=128, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
    codex_visual_model: str | None = Field(default=None, max_length=128, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
    openai_visual_model: str | None = Field(default=None, max_length=128, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:-]*$")
    gemini_model: GoogleModel | None = None
    gemini_visual_model: GoogleModel | None = None
    agy_model: GoogleModel | None = None
    agy_visual_model: GoogleModel | None = None
    api_key: SecretStr | None = Field(default=None, max_length=1024)
    google_api_key: SecretStr | None = Field(default=None, max_length=1024)
    remove_key: bool = False
    remove_google_key: bool = False


class Blob(ctypes.Structure):
    _fields_ = [("size", ctypes.c_uint32), ("buffer", ctypes.c_void_p)]


def crypt(data: bytes, encrypt: bool):
    if os.name != "nt":
        raise HTTPException(422, tr("Dùng biến môi trường để đặt API key trên hệ điều hành này.", "Set your API key through an environment variable on this operating system."))
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.c_void_p))
    target = Blob()
    library = ctypes.windll.crypt32
    operation = library.CryptProtectData if encrypt else library.CryptUnprotectData
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise HTTPException(503, tr("Windows không thể mở hoặc lưu khóa cho tài khoản hiện tại.", "Windows could not read or save the key for the current account."))
    try:
        return ctypes.string_at(target.buffer, target.size)
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.c_void_p(target.buffer))


def updated(current, body):
    record = dict(current, provider=body.provider)
    for field in ("visual_provider", "codex_model", "codex_visual_model", "openai_visual_model",
                  "gemini_model", "gemini_visual_model", "agy_model", "agy_visual_model"):
        if field in body.model_fields_set:
            record[field] = getattr(body, field)
    for field, secret, remove in (("key", body.api_key, body.remove_key),
                                  ("google_key", body.google_api_key, body.remove_google_key)):
        if remove:
            record.pop(field, None)
        elif secret is not None:
            value = secret.get_secret_value().strip()
            if not value or not value.isascii() or any(c.isspace() for c in value):
                raise HTTPException(422, tr("API key không hợp lệ.", "Invalid API key."))
            record[field] = base64.b64encode(crypt(value.encode(), True)).decode()
    return record


def google_environment_key():
    return os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")


def api_key(record, *, google=False):
    field = "google_key" if google else "key"
    if record.get(field):
        return crypt(base64.b64decode(record[field]), False).decode()
    return google_environment_key() if google else os.getenv("OPENAI_API_KEY")


def cli_environment():
    return {k:v for k,v in os.environ.items()
            if k.upper() not in {"OPENAI_API_KEY", "CODEX_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"}}


def cli_status(executable, *, timeout=8):
    if not executable:
        return "missing"
    try:
        result = subprocess.run([executable, "login", "status"], capture_output=True, timeout=timeout,
                                env=cli_environment(), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode == 0:
            return "ready"
        return "logged_out" if b"not logged in" in (result.stdout+result.stderr).lower() else "unknown"
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"


def codex_models(executable):
    if not executable:
        return []
    cache = Path(os.environ.get("CODEX_HOME") or Path.home()/".codex") / "models_cache.json"
    try:
        catalog = json.loads(cache.read_text(encoding="utf-8"))["models"]
    except (OSError, ValueError, KeyError, TypeError):
        try:
            result = subprocess.run([executable,"debug","models","--bundled"],capture_output=True,
                                    timeout=5,check=True,env=cli_environment(),
                                    creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            catalog = json.loads(result.stdout)["models"]
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
            return []
    if not isinstance(catalog,list):
        return []
    return [dict(id=m["slug"],name=m.get("display_name") or m["slug"]) for m in catalog
            if isinstance(m,dict) and m.get("slug") and m.get("visibility")=="list"]


def public_settings(record):
    executable = shutil.which("codex")
    return dict(provider=record.get("provider","openai"), saved_key=bool(record.get("key")),
                environment_key=bool(os.getenv("OPENAI_API_KEY")), codex=cli_status(executable),
                codex_models=codex_models(executable), agy_available=bool(shutil.which("agy")),
                google_saved_key=bool(record.get("google_key")), google_environment_key=bool(google_environment_key()),
                **{field: record.get(field) for field in ("visual_provider", "codex_model", "codex_visual_model",
                    "openai_visual_model", "gemini_model", "gemini_visual_model", "agy_model", "agy_visual_model")})


def codex_request(schema, instructions, context):
    schema_text = json.dumps(to_strict_json_schema(schema))
    prefix = instructions + "\n\n" + prompt("providers/codex-context") + "\n"
    return schema_text, prefix + codex_context(context)


def codex_context(context):
    return json.dumps(context, ensure_ascii=False)


def validation_issues(error):
    issues = error.errors(include_url=False, include_context=False, include_input=False)
    return ", ".join(
        f"{'.'.join(map(str, issue['loc'])) or 'root'} ({issue['type']}): {issue['msg']}"
        for issue in issues[:5]
    )


def codex_result(schema, instructions, context, search=False, *, model=None, budget=None, renew=None, kind="tutor",
                 pre_send=None, remaining=None, search_events=None):
    schema_text, prompt_text = codex_request(schema, instructions, context)
    size = len(schema_text.encode()) + len(prompt_text.encode())
    measurement = budget.measure(size, kind) if budget else nullcontext({})
    with measurement as usage:
        if renew:
            renew()
        options = {"remaining": remaining} if remaining else {}
        if search_events is not None:
            options["search_events"] = search_events
        return run_codex(schema, schema_text, prompt_text, search, model, usage, pre_send=pre_send, **options)


def run_codex(schema, schema_text, prompt_text, search, model, usage, *, pre_send=None, remaining=None,
              search_events=None):
    exe = shutil.which("codex")
    status = cli_status(exe, timeout=min(8, remaining())) if remaining else cli_status(exe)
    if status == "missing":
        raise HTTPException(503, tr("Chưa tìm thấy Codex CLI trong PATH của máy chủ.", "Codex CLI was not found on the server PATH."))
    if status == "logged_out":
        raise HTTPException(503, tr("Chạy codex login trên máy này rồi thử lại.", "Run codex login on this machine and try again."))
    with tempfile.TemporaryDirectory(prefix="study-codex-") as folder:
        schema_file = Path(folder) / "schema.json"
        schema_file.write_text(schema_text, encoding="utf-8")
        args = [exe, "-a", "never", "-c", 'web_search="'+("live" if search else "disabled")+'"',
                "-c", "features.shell_tool=false", "exec", "--ignore-user-config", "--ephemeral",
                "--skip-git-repo-check", "--sandbox", "read-only", "--json", "--output-schema", str(schema_file)]
        if model:
            args.extend(["--model", model])
        args.append("-")
        try:
            if pre_send:
                pre_send()
            result = subprocess.run(args,input=prompt_text,encoding="utf-8",errors="replace",capture_output=True,
                                    timeout=remaining() if remaining else 180,cwd=folder,env=cli_environment(),
                                    creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        except subprocess.TimeoutExpired:
            raise HTTPException(504,tr("Codex CLI trả lời quá chậm. Hãy thử lại.", "Codex CLI timed out. Please try again."))
        except OSError:
            raise HTTPException(503,tr("Không khởi chạy được Codex CLI.", "Could not start Codex CLI."))
        if remaining:
            remaining()
        if result.returncode:
            log.warning("Codex CLI failed for %s with exit code %d", schema.__name__, result.returncode)
            raise HTTPException(502,tr("Codex CLI gặp lỗi. Kiểm tra đăng nhập, phiên bản CLI và hạn mức rồi thử lại.", "Codex CLI failed. Check your sign-in, CLI version, and quota, then try again."))
        try:
            events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
            for event in events:
                if event.get("type") == "turn.completed":
                    reported = event.get("usage") or {}
                    usage.update({key: value for key, value in reported.items()
                                  if key in ("input_tokens", "output_tokens") and type(value) is int})
            items = [event["item"] for event in events if event.get("type")=="item.completed"]
            searches = [item for item in items if item["type"] == "web_search"]
            completed_searches = sum(item.get("status", "completed") == "completed" for item in searches)
            if search_events is not None:
                search_events["completed"] = completed_searches
                observed_search = any((event.get("item") or {}).get("type") == "web_search" for event in events)
                verified = bool(completed_searches) and completed_searches == len(searches)
                search_mismatch = not verified if search else observed_search
            else:
                search_mismatch = search and not searches
            if search_mismatch:
                raise HTTPException(502,tr("Codex chưa tra cứu được web. Hãy thử lại.", "Codex could not search the web. Please try again."))
            message = next(item["text"] for item in reversed(items) if item["type"]=="agent_message")
            return schema.model_validate_json(message).model_dump()
        except (ValueError, KeyError, StopIteration, TypeError, AttributeError) as exc:
            detail = validation_issues(exc) if isinstance(exc, ValidationError) else type(exc).__name__
            log.warning("Codex CLI returned invalid %s output: %s", schema.__name__, detail)
            raise HTTPException(502,tr("Codex CLI chưa trả về nội dung hợp lệ. Hãy thử lại.", "Codex CLI returned invalid content. Please try again.")) from exc
