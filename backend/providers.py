from .language import tr
import base64
import ctypes
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Literal
from .prompt_files import prompt

from fastapi import HTTPException
from pydantic import BaseModel, Field, SecretStr
from openai.lib._pydantic import to_strict_json_schema


class SettingsUpdate(BaseModel):
    provider: Literal["openai", "codex"]
    codex_model: str | None = Field(default=None, max_length=128, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
    api_key: SecretStr | None = Field(default=None, max_length=1024)
    remove_key: bool = False


class Blob(ctypes.Structure):
    _fields_ = [("size", ctypes.c_uint32), ("buffer", ctypes.c_void_p)]


def crypt(data: bytes, encrypt: bool):
    if os.name != "nt":
        raise HTTPException(422, tr("Hãy cấu hình OPENAI_API_KEY bằng biến môi trường trên hệ điều hành này.", "Set the OPENAI_API_KEY environment variable on this operating system."))
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
    if "codex_model" in body.model_fields_set:
        record["codex_model"] = body.codex_model
    if body.remove_key:
        record.pop("key", None)
    elif body.api_key is not None:
        value = body.api_key.get_secret_value().strip()
        if not value or not value.isascii() or any(c.isspace() for c in value):
            raise HTTPException(422, tr("API key không hợp lệ.", "Invalid API key."))
        record["key"] = base64.b64encode(crypt(value.encode(), True)).decode()
    return record


def api_key(record):
    if record.get("key"):
        return crypt(base64.b64decode(record["key"]), False).decode()
    return os.getenv("OPENAI_API_KEY")


def cli_environment():
    return {k:v for k,v in os.environ.items() if k.upper() not in {"OPENAI_API_KEY","CODEX_API_KEY"}}


def cli_status(executable):
    if not executable:
        return "missing"
    try:
        result = subprocess.run([executable, "login", "status"], capture_output=True, timeout=8,
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
                codex_model=record.get("codex_model"), codex_models=codex_models(executable))


def codex_result(schema, instructions, context, search=False, *, model=None):
    exe = shutil.which("codex")
    status = cli_status(exe)
    if status == "missing":
        raise HTTPException(503, tr("Chưa tìm thấy Codex CLI trong PATH của máy chủ.", "Codex CLI was not found on the server PATH."))
    if status == "logged_out":
        raise HTTPException(503, tr("Chạy codex login trên máy này rồi thử lại.", "Run codex login on this machine and try again."))
    with tempfile.TemporaryDirectory(prefix="study-codex-") as folder:
        schema_file = Path(folder) / "schema.json"
        schema_file.write_text(json.dumps(to_strict_json_schema(schema)),encoding="utf-8")
        args = [exe, "-a", "never", "-c", 'web_search="'+("live" if search else "disabled")+'"',
                "-c", "features.shell_tool=false", "exec", "--ignore-user-config", "--ephemeral",
                "--skip-git-repo-check", "--sandbox", "read-only", "--json", "--output-schema", str(schema_file)]
        if model:
            args.extend(["--model", model])
        args.append("-")
        prompt_text = instructions+"\n\n"+prompt("providers/codex-context")+"\n"+json.dumps(context,ensure_ascii=False)
        try:
            result = subprocess.run(args,input=prompt_text,encoding="utf-8",errors="replace",capture_output=True,
                                    timeout=180,cwd=folder,env=cli_environment(),
                                    creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        except subprocess.TimeoutExpired:
            raise HTTPException(504,tr("Codex CLI trả lời quá chậm. Hãy thử lại.", "Codex CLI timed out. Please try again."))
        except OSError:
            raise HTTPException(503,tr("Không khởi chạy được Codex CLI.", "Could not start Codex CLI."))
        if result.returncode:
            raise HTTPException(502,tr("Codex CLI gặp lỗi. Kiểm tra đăng nhập, phiên bản CLI và hạn mức rồi thử lại.", "Codex CLI failed. Check your sign-in, CLI version, and quota, then try again."))
        try:
            events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
            items = [event["item"] for event in events if event.get("type")=="item.completed"]
            if search and not any(item["type"]=="web_search" for item in items):
                raise HTTPException(502,tr("Codex chưa tra cứu được web. Hãy thử lại.", "Codex could not search the web. Please try again."))
            message = next(item["text"] for item in reversed(items) if item["type"]=="agent_message")
            return schema.model_validate_json(message).model_dump()
        except (ValueError, KeyError, StopIteration) as exc:
            raise HTTPException(502,tr("Codex CLI chưa trả về nội dung hợp lệ. Hãy thử lại.", "Codex CLI returned invalid content. Please try again.")) from exc
