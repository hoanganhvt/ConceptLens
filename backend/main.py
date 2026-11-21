import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field
from urllib.parse import urlsplit
from . import ai, providers
from .prompt_files import prompt
from .demo import ROAD, SAMPLE, ROAD_EN, SAMPLE_EN
from .language import language, tr
from .models import Roadmap, Lesson, Illustration, Motion
from .physics import grade, motion

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.getenv("STUDY_DATA", ROOT / "data"))
DATA.mkdir(exist_ok=True, parents=True)
app = FastAPI(docs_url=None, redoc_url=None)
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
    conn.execute("CREATE TABLE IF NOT EXISTS records (key TEXT PRIMARY KEY, value TEXT NOT NULL)")


def get(key, default=None):
    with db() as conn:
        row = conn.execute("SELECT value FROM records WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def put(key, value):
    with db() as conn:
        conn.execute("INSERT OR REPLACE INTO records VALUES (?,?)", (key,json.dumps(value,ensure_ascii=False)))
    return value


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
    return dict(doc=get("lesson:"+key),progress=get("progress:"+key,{}),notes=get("notes:"+key,[]),
                main=get("thread:"+key+":main",[]),scroll=get("scroll:"+key,0))


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


@app.post("/api/quiz/{rid}/{tid}")
def quiz(rid:str,tid:str,body:Attempt):
    doc = lesson_for(rid,tid)
    if body.question >= len(doc["quiz"]):
        raise HTTPException(422,tr("Không tìm thấy câu hỏi.", "Question not found."))
    question = doc["quiz"][body.question]
    try:
        correct = grade(question,body.answer)
    except ValueError as exc:
        raise HTTPException(422,str(exc))
    key = f"progress:{rid}:{tid}"
    with locks[hash(key)%len(locks)]:
        progress = get(key,{})
        progress.setdefault(str(body.question),[]).append(dict(answer=body.answer,correct=correct,explanation=question["explanation"]))
        return put(key,progress)


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


def thread(rid,tid,branch):
    doc = lesson_for(rid,tid)
    ctx = dict(topic=topic_for(rid,tid)[1],sections=doc["sections"],illustrations=[
        {k:x[k] for k in ("title","instruction","explanation")} for x in doc["illustrations"]])
    if branch != "main":
        note = next((n for n in get(f"notes:{rid}:{tid}",[]) if n["id"]==branch),None)
        if not note:
            raise HTTPException(404,tr("Không tìm thấy highlight.", "Highlight not found."))
        ctx.update(highlight=note)
    return f"thread:{rid}:{tid}:{branch}",ctx


@app.get("/api/chat/{rid}/{tid}/{branch}")
def read_chat(rid:str,tid:str,branch:str):
    key,_ = thread(rid,tid,branch)
    return get(key,[])


@app.post("/api/chat/{rid}/{tid}/{branch}")
def send(rid:str,tid:str,branch:str,body:Message):
    key,ctx = thread(rid,tid,branch)
    with locks[hash(key)%len(locks)]:
        history = get(key,[])
        reply = ai.chat(ctx,history,body.text,body.search,settings=ai_settings())
        return put(key,[*history,dict(role="user",text=body.text),reply])


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
        replacement = ai.structured(Illustration,prompt("illustrations/contract", "lessons/generate", "illustrations/repair"),dict(item=item,error=body.error),settings=ai_settings())
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

