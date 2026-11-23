import asyncio
import json
import logging
import os
import re
import sqlite3
from contextlib import asynccontextmanager, contextmanager, nullcontext
from pathlib import Path
from threading import Lock
from typing import Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field, StrictBool
from urllib.parse import urlsplit
from . import ai, chat_state, learner_memory, memory_retrieval, providers, tutor_agent, tutor_context
from .embedding_process import EncoderProcess
from .prompt_files import prompt
from .demo import ROAD, SAMPLE, ROAD_EN, SAMPLE_EN
from .language import language, tr
from .models import Roadmap, Lesson, Illustration, Motion
from .physics import assess, motion

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.getenv("STUDY_DATA", ROOT / "data"))
DATA.mkdir(exist_ok=True, parents=True)
memory_encoder = EncoderProcess(os.getenv("STUDY_EMBEDDING_MODEL_DIR"))


def maintain_memory_index(db, encoder):
    if os.getenv("STUDY_BOUNDED_CONTEXT") == "1":
        memory_retrieval.sync(db, encoder)
    else:
        encoder.close()


@asynccontextmanager
async def lifespan(app):
    stop = asyncio.Event()

    async def collect(action, name, *args):
        while not stop.is_set():
            try:
                await run_in_threadpool(action, db, *args)
            except Exception as exc:
                logging.getLogger(__name__).warning("%s unavailable (%s)", name, type(exc).__name__)
            try:
                await asyncio.wait_for(stop.wait(), timeout=1)
            except TimeoutError:
                pass

    workers = (asyncio.create_task(collect(learner_memory.process_pending, "Learner memory worker")),
               asyncio.create_task(collect(maintain_memory_index, "Memory index worker", memory_encoder)))
    try:
        yield
    finally:
        stop.set()
        await asyncio.gather(*workers)
        await run_in_threadpool(memory_encoder.close)


app = FastAPI(docs_url=None, redoc_url=None, lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost","127.0.0.1","testserver"])
locks = [Lock() for _ in range(127)]


@app.middleware("http")
async def local_origin(request: Request, call_next):
    token = language.set("en" if request.headers.get("X-Study-Language") == "en" else "vi")
    try:
        return await check_origin(request, call_next)
    finally:
        language.reset(token)


async def check_origin(request, call_next):
    origin = request.headers.get("origin")
    if request.method != "GET" and origin and urlsplit(origin).netloc != request.headers.get("host"):
        return JSONResponse({"detail":tr("Nguồn yêu cầu không hợp lệ.", "Invalid request origin.")}, 403)
    return await call_next(request)


@contextmanager
def db():
    conn = sqlite3.connect(DATA / "study.sqlite", timeout=15)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


with db() as conn:
    conn.execute("BEGIN IMMEDIATE")
    conn.execute("CREATE TABLE IF NOT EXISTS records (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version < 1:
        chat_state.migrate(conn)
        conn.execute("PRAGMA user_version=1")
    if version < 2:
        learner_memory.migrate(conn)
        conn.execute("PRAGMA user_version=2")
    if version < 3:
        memory_retrieval.migrate(conn)
        conn.execute("PRAGMA user_version=3")


def get_record(conn, key, default=None):
    row = conn.execute("SELECT value FROM records WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def put_record(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO records VALUES (?,?)", (key, json.dumps(value, ensure_ascii=False)))
    return value


def get(key, default=None):
    with db() as conn:
        return get_record(conn, key, default)


def put(key, value):
    with db() as conn:
        return put_record(conn, key, value)


def unique():
    return uuid4().hex


def ai_settings():
    return get("ai-settings", {"provider":"openai"})


@app.get("/api/settings")
def settings():
    return providers.public_settings(ai_settings())


settings_lock = Lock()


@app.post("/api/settings")
def save_settings(body: providers.SettingsUpdate):
    with settings_lock:
        record = put("ai-settings", providers.updated(ai_settings(), body))
    return providers.public_settings(record)


def write_road(road):
    folder = DATA / road["id"]
    folder.mkdir(exist_ok=True)
    temp = folder / (unique()+".tmp")
    temp.write_text(json.dumps(road,ensure_ascii=False,indent=2),encoding="utf-8")
    temp.replace(folder / "roadmap.json")


def road_for(rid):
    if rid not in ("vat-ly", "physics") and (len(rid) != 32 or any(c not in "0123456789abcdef" for c in rid)):
        raise HTTPException(404,tr("Không tìm thấy lộ trình.", "Roadmap not found."))
    path = DATA / rid / "roadmap.json"
    if not path.is_file():
        raise HTTPException(404,tr("Không tìm thấy lộ trình.", "Roadmap not found."))
    return json.loads(path.read_text(encoding="utf-8"))


if not (DATA/"vat-ly"/"roadmap.json").exists():
    write_road(dict(ROAD,id="vat-ly"))
if not get("lesson:vat-ly:roi-tu-do"):
    put("lesson:vat-ly:roi-tu-do", dict(SAMPLE,version=unique()))


if not (DATA/"physics"/"roadmap.json").exists():
    write_road(dict(ROAD_EN, id="physics"))
if not get("lesson:physics:free-fall"):
    put("lesson:physics:free-fall", dict(SAMPLE_EN, version=unique()))


def topic_for(rid, tid):
    road = road_for(rid)
    for chapter in road["chapters"]:
        for topic in chapter["topics"]:
            if topic["id"] == tid:
                return road,topic
    raise HTTPException(404,tr("Không tìm thấy bài.", "Lesson not found."))


def lesson_for(rid,tid):
    doc = get(f"lesson:{rid}:{tid}")
    if not doc:
        raise HTTPException(404,tr("Chưa tạo bài giảng.", "This lesson has not been generated yet."))
    return doc


@app.get("/api/roads")
def roads():
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(DATA.glob("*/roadmap.json"), key=lambda p:p.stat().st_mtime, reverse=True)
            if p.parent.name != tr("physics", "vat-ly")]


class Draft(BaseModel):
    subject: str = Field(min_length=1,max_length=500)
    level: str
    goal: str
    schedule: str
    revision: str = ""
    previous: Roadmap | None = None


@app.post("/api/drafts")
def draft(body: Draft):
    return ai.structured(Roadmap,prompt("roadmaps/draft"),body.model_dump(),settings=ai_settings())


@app.post("/api/roads")
def commit(body: Roadmap):
    road = dict(body.model_dump(),id=unique())
    for chapter in road["chapters"]:
        for topic in chapter["topics"]:
            topic["id"] = unique()
    write_road(road)
    return road


@app.get("/api/lesson/{rid}/{tid}")
def read(rid:str,tid:str):
    topic_for(rid,tid)
    key = f"{rid}:{tid}"
    with db() as conn:
        conn.execute("BEGIN")
        doc = get_record(conn, "lesson:"+key)
        progress = get_record(conn, "progress:"+key, {})
        if doc:
            learner_memory.mark_eligible(conn, rid, doc, progress)
        return dict(doc=doc, progress=progress, notes=get_record(conn, "notes:"+key, []),
                    main=get_record(conn, "thread:"+key+":main", []), scroll=get_record(conn, "scroll:"+key, 0))


@app.post("/api/lesson/{rid}/{tid}")
def generate(rid:str,tid:str):
    road,topic = topic_for(rid,tid)
    key = f"lesson:{rid}:{tid}"
    with locks[hash(key)%len(locks)]:
        existing = get(key)
        if existing:
            return existing
        doc = ai.structured(Lesson,prompt("illustrations/contract", "lessons/generate"),dict(road=road,topic=topic),settings=ai_settings())
        return put(key,dict(doc,version=unique()))


class Attempt(BaseModel):
    question:int = Field(ge=0)
    answer:str = Field(min_length=1,max_length=300)
    attempt_id: UUID | None = None


@app.post("/api/quiz/{rid}/{tid}")
def quiz(rid:str,tid:str,body:Attempt):
    topic_for(rid, tid)
    key = f"progress:{rid}:{tid}"
    attempt_id = str(body.attempt_id or uuid4())
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        doc = get_record(conn, f"lesson:{rid}:{tid}")
        if not doc:
            raise HTTPException(404,tr("Chưa tạo bài giảng.", "This lesson has not been generated yet."))
        progress = get_record(conn, key, {})
        prior = learner_memory.source(conn, attempt_id)
        if prior:
            same_source = tuple(prior[k] for k in ("roadmap_id", "topic_id", "lesson_version", "question"))
            saved, _ = learner_memory.quiz_attempt(conn, prior)
            if same_source != (rid, tid, doc["version"], body.question) or not saved or saved["answer"] != body.answer:
                raise HTTPException(409, tr("Mã lần làm đã được dùng cho đáp án khác.", "This attempt ID already belongs to a different submission."))
            return learner_memory.mark_eligible(conn, rid, doc, progress)
        if body.question >= len(doc["quiz"]):
            raise HTTPException(422,tr("Không tìm thấy câu hỏi.", "Question not found."))
        question = doc["quiz"][body.question]
        try:
            correct, diagnostic, dimension = assess(question, body.answer)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        attempts = progress.setdefault(str(body.question), [])
        learner_memory.add_submission(conn, attempt_id, rid, tid, doc["version"], body.question,
                                      len(attempts), diagnostic, dimension)
        attempts.append(dict(answer=body.answer, correct=correct, explanation=question["explanation"], attempt_id=attempt_id))
        put_record(conn, key, progress)
        return learner_memory.mark_eligible(conn, rid, doc, progress)


def memory_road_title(rid):
    try:
        return road_for(rid)["title"]
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        return None


class MemoryText(BaseModel):
    statement: str = Field(min_length=1, max_length=2000)


class NewMemory(MemoryText):
    kind: Literal["goal", "preference"]


class EditMemory(MemoryText):
    revision: int = Field(ge=1, strict=True)


class MemoryCapture(BaseModel):
    enabled: StrictBool


class ResumeMemory(BaseModel):
    attempt_id: UUID


def memory_statement(body):
    text = body.statement.strip()
    if not text:
        raise HTTPException(422, tr("Hãy nhập nội dung bộ nhớ.", "Enter the memory text."))
    return text


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    if request.url.path == "/api/memories" or request.url.path.startswith("/api/memories/"):
        return JSONResponse({"detail": tr("Dữ liệu bộ nhớ không hợp lệ.", "Invalid learner memory input.")}, 422)
    return await request_validation_exception_handler(request, exc)


def memory_list(conn):
    result = learner_memory.list_memories(conn, memory_road_title)
    result["encoder_status"] = memory_retrieval.encoder_status(conn, memory_encoder)
    return result


@app.get("/api/memories")
def memories():
    with db() as conn:
        conn.execute("BEGIN")
        return memory_list(conn)


@app.post("/api/memories")
def create_memory(body: NewMemory):
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        learner_memory.create(conn, body.kind, memory_statement(body))
        return memory_list(conn)


@app.put("/api/memories/capture")
def capture_memory(body: MemoryCapture):
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        learner_memory.set_enabled(conn, body.enabled)
        return memory_list(conn)


@app.post("/api/memories/resume")
def resume_memory(body: ResumeMemory):
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        learner_memory.resume(conn, str(body.attempt_id))
        return memory_list(conn)


@app.get("/api/memories/{memory_id}")
def read_memory(memory_id: str, revision: int = Query(ge=1)):
    with db() as conn:
        conn.execute("BEGIN")
        row = learner_memory.record(conn, memory_id, revision)
        source = memory_retrieval.provenance(conn, row)
        if not source:
            raise learner_memory.not_found()
        memory = learner_memory.public_memory(conn, row, memory_road_title)
        memory["evidence"] = [ref for ref in memory["evidence"] if ref["attempt_id"] in source.get("attempt_ids", ())]
        return memory


@app.patch("/api/memories/{memory_id}")
def edit_memory(memory_id: str, body: EditMemory):
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        learner_memory.edit(conn, memory_id, body.revision, memory_statement(body))
        return memory_list(conn)


@app.delete("/api/memories/{memory_id}")
def forget_memory(memory_id: str, revision: int = Query(ge=1)):
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        learner_memory.forget(conn, memory_id, revision)
        return memory_list(conn)


@app.get("/api/memories/{memory_id}/evidence/{attempt_id}")
def read_memory_evidence(memory_id: str, attempt_id: UUID):
    with db() as conn:
        conn.execute("BEGIN")
        return learner_memory.evidence_detail(conn, memory_id, str(attempt_id))


class Anchor(BaseModel):
    version:str
    block:str
    start:int = Field(ge=0)
    end:int = Field(gt=0)
    quote:str = Field(min_length=1,max_length=12000)
    snapshot:dict[str,float] | None = None


def blocks(doc):
    result = {"intro":doc["intro"]}
    result.update({f"s{i}":s["text"] for i,s in enumerate(doc["sections"])})
    for i,item in enumerate(doc["illustrations"]):
        result[f"i{i}"] = item["instruction"]
        result[f"e{i}"] = item["explanation"]
    return result


@app.post("/api/notes/{rid}/{tid}")
def note(rid:str,tid:str,body:Anchor):
    doc = lesson_for(rid,tid)
    block = blocks(doc).get(body.block,"")
    # Browser Range offsets use UTF-16 code units.
    selected = block.encode("utf-16-le")[2*body.start:2*body.end].decode("utf-16-le",errors="replace")
    if body.version != doc["version"] or body.end*2 > len(block.encode("utf-16-le")) or selected != body.quote:
        raise HTTPException(422,tr("Đoạn chọn đã thay đổi.", "The selected passage has changed."))
    key = f"notes:{rid}:{tid}"
    with locks[hash(key)%len(locks)]:
        notes = get(key,[])
        prior = next((n for n in notes if all(n[k]==getattr(body,k) for k in ("block","start","end","version","snapshot"))),None)
        if prior:
            return prior
        item = dict(body.model_dump(),id=unique())
        put(key,[*notes,item])
        return item


class Message(BaseModel):
    text:str = Field(min_length=1,max_length=12000)
    search:bool = False
    request_id: UUID | None = None


def thread(rid,tid,branch):
    doc = lesson_for(rid,tid)
    topic = topic_for(rid,tid)[1]
    note = None
    if branch != "main" and not re.fullmatch(r"question-[a-f0-9]{32}", branch):
        note = next((n for n in get(f"notes:{rid}:{tid}",[]) if n["id"]==branch),None)
        if not note:
            raise HTTPException(404,tr("Không tìm thấy highlight.", "Highlight not found."))
    return f"thread:{rid}:{tid}:{branch}", doc, topic, note


@app.get("/api/chat/{rid}/{tid}")
def chat_threads(rid: str, tid: str):
    topic_for(rid, tid)
    lesson_for(rid, tid)
    prefix = f"thread:{rid}:{tid}:"
    with db() as conn:
        rows = conn.execute("SELECT key, value FROM records WHERE key GLOB ? ORDER BY rowid DESC", (prefix + "*",))
        threads = []
        for key, value in rows:
            question = next((msg["text"] for msg in json.loads(value) if msg["role"] == "user"), "")
            if question.strip():
                threads.append({"id": key[len(prefix):], "question": question.strip()[:180]})
        return threads


@app.get("/api/chat/{rid}/{tid}/{branch}")
def read_chat(rid:str,tid:str,branch:str):
    key, *_ = thread(rid,tid,branch)
    return get(key,[])


@app.post("/api/chat/{rid}/{tid}/{branch}")
def send(rid:str,tid:str,branch:str,body:Message):
    agent = tutor_agent.Turn() if os.getenv("STUDY_TUTOR_AGENT") == "1" else nullcontext()
    with agent as turn:
        return send_turn(rid, tid, branch, body, turn)


def send_turn(rid, tid, branch, body, turn):
    key, doc, topic, note = thread(rid, tid, branch)
    reservation = chat_state.Send(db, key, body.request_id, body.text, body.search)
    history, replay = reservation.reserve()
    if replay:
        if turn:
            turn.reason = "replay"
        return history
    try:
        settings = ai_settings()
        working = None
        model_history = tutor_context.model_history(history)
        if os.getenv("STUDY_BOUNDED_CONTEXT") == "1":
            provider = settings.get("provider", "openai")
            model = (settings.get("codex_model") or "default") if provider == "codex" else ai.MODEL
            budget = tutor_context.Budget(provider, model)
            ctx, optional = tutor_context.evidence(
                doc, topic, note, get(f"progress:{rid}:{tid}", {}),
                lambda index: get(f"motion:{rid}:{tid}:{index}"), body.text)
            current_note = note if note and note["version"] == doc["version"] else None
            generation, memories = memory_retrieval.retrieve(db, memory_encoder, rid, topic, current_note, body.text)
            working = tutor_context.WorkingContext(db, rid, tid, branch, ctx, optional, model_history, budget,
                                                   generation=generation, memories=memories)
        else:
            ctx = dict(topic=topic, sections=doc["sections"], illustrations=[
                {k: x[k] for k in ("title", "instruction", "explanation")} for x in doc["illustrations"]])
            if note:
                ctx["highlight"] = note
                if turn and note["version"] == doc["version"]:
                    values = tutor_context.finite_values(note.get("snapshot") or {}, tutor_context.MOTION_UNITS)
                    if values:
                        ctx["simulation"] = {"source": "highlight", "values": values,
                                             "units": {key: tutor_context.MOTION_UNITS[key] for key in values}}
        chat = tutor_agent.chat if turn else ai.chat
        options = {"turn": turn} if turn else {}
        reply = chat(ctx, model_history, body.text, body.search, settings=settings, working=working,
                     renew=reservation.renew, **options)
        if working and working.sent:
            reply["memory_refs"] = working.sent
        commit = {"pre_commit": turn.remaining} if turn else {}
        result = reservation.commit(dict(role="user", text=body.text), reply, working.pending if working else None,
                                    verify=working.verify if working and working.sent else None, **commit)
    except BaseException:
        reservation.release()
        raise
    return result


class Playback(BaseModel):
    params:Motion
    index:int = Field(ge=0,le=240)


def visual(rid,tid,index):
    doc = lesson_for(rid,tid)
    if not 0 <= index < len(doc["illustrations"]):
        raise HTTPException(404,tr("Không tìm thấy minh họa.", "Illustration not found."))
    return doc,doc["illustrations"][index]


@app.post("/api/motion/{rid}/{tid}/{index}")
def simulate(rid:str,tid:str,index:int,body:Playback):
    _,item = visual(rid,tid,index)
    if item["mode"] != "motion":
        raise HTTPException(422,tr("Minh họa không dùng mô phỏng động học.", "This illustration does not use the motion simulation."))
    result = dict(motion(body.params),index=body.index)
    return put(f"motion:{rid}:{tid}:{index}",result)


@app.get("/api/motion/{rid}/{tid}/{index}")
def replay(rid:str,tid:str,index:int):
    visual(rid,tid,index)
    return get(f"motion:{rid}:{tid}:{index}",dict(motion(Motion()),index=0))


class Repair(BaseModel):
    error:str = Field(max_length=600)
    manual:bool = False


@app.post("/api/repair/{rid}/{tid}/{index}")
def repair(rid:str,tid:str,index:int,body:Repair):
    key = f"lesson:{rid}:{tid}"
    with locks[hash(key)%len(locks)]:
        doc,item = visual(rid,tid,index)
        marker = f"repaired:{rid}:{tid}:{index}"
        if get(marker) and not body.manual:
            raise HTTPException(409,tr("Đã thử sửa minh họa. Bạn có thể tạo lại.", "An automatic repair was already attempted. You can regenerate the illustration."))
        if not body.manual:
            put(marker,True)
        replacement = ai.structured(Illustration,prompt("illustrations/contract", "illustrations/repair"),dict(item=item,error=body.error),settings=ai_settings())
        for field in ("html","css","js"):
            item[field] = replacement[field]
        put(key,doc)
        return item


class Position(BaseModel):
    y:int = Field(ge=0,le=10000000)


@app.post("/api/scroll/{rid}/{tid}")
def save_scroll(rid:str,tid:str,body:Position):
    lesson_for(rid,tid)
    return put(f"scroll:{rid}:{tid}",body.y)


if (ROOT/"dist").is_dir():
    app.mount("/",StaticFiles(directory=ROOT/"dist",html=True),name="web")

