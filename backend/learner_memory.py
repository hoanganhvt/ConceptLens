"""Local learner memories, projected from committed quiz submissions."""

import json
import logging
import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import HTTPException

from .chat_state import OWNER
from .language import language, tr
from .physics import assess


def migrate(conn):
    conn.execute("""CREATE TABLE learner_memory_settings (
        owner TEXT PRIMARY KEY, enabled INTEGER NOT NULL, generation INTEGER NOT NULL,
        processed_through INTEGER NOT NULL)""")
    conn.execute("""CREATE TABLE quiz_submissions (
        seq INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL, id TEXT NOT NULL,
        roadmap_id TEXT NOT NULL, topic_id TEXT NOT NULL, lesson_version TEXT NOT NULL,
        question INTEGER NOT NULL, position INTEGER NOT NULL, observed_at TEXT NOT NULL,
        generation INTEGER, language TEXT NOT NULL, UNIQUE(owner, id))""")
    conn.execute("""CREATE TABLE learner_memories (
        owner TEXT NOT NULL, id TEXT NOT NULL, kind TEXT NOT NULL, statement TEXT NOT NULL,
        roadmap_id TEXT, diagnostic TEXT, dimension TEXT, language TEXT NOT NULL,
        status TEXT NOT NULL, revision INTEGER NOT NULL, created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL, PRIMARY KEY(owner, id),
        UNIQUE(owner, roadmap_id, diagnostic, dimension))""")
    conn.execute("""CREATE TABLE learner_memory_evidence (
        owner TEXT NOT NULL, memory_id TEXT NOT NULL, submission_seq INTEGER NOT NULL,
        PRIMARY KEY(owner, submission_seq))""")
    conn.execute("CREATE INDEX learner_evidence_by_memory ON learner_memory_evidence(owner, memory_id)")
    conn.execute("""CREATE TABLE learner_memory_pending (
        owner TEXT NOT NULL, submission_seq INTEGER NOT NULL, diagnostic TEXT NOT NULL,
        dimension TEXT NOT NULL, expected_revision INTEGER, failures INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(owner, submission_seq))""")
    conn.execute("""CREATE TABLE learner_memory_suppression (
        owner TEXT NOT NULL, roadmap_id TEXT NOT NULL, diagnostic TEXT NOT NULL,
        dimension TEXT NOT NULL, cutoff INTEGER NOT NULL, suppressed INTEGER NOT NULL,
        PRIMARY KEY(owner, roadmap_id, diagnostic, dimension))""")


def rows(conn, query, params):
    cursor = conn.cursor()
    cursor.row_factory = sqlite3.Row
    return cursor.execute(query, params)


def now():
    return datetime.now(UTC).isoformat()


def settings(conn, owner=OWNER):
    row = conn.execute("""SELECT enabled, generation, processed_through
        FROM learner_memory_settings WHERE owner=?""", (owner,)).fetchone()
    return row or (0, 0, 0)


def set_enabled(conn, enabled, owner=OWNER):
    previous, generation, processed = settings(conn, owner)
    if previous and not enabled:
        generation += 1
        conn.execute("DELETE FROM learner_memory_pending WHERE owner=?", (owner,))
    conn.execute("""INSERT OR REPLACE INTO learner_memory_settings VALUES (?, ?, ?, ?)""",
                 (owner, enabled, generation, processed))


def source(conn, attempt_id, owner=OWNER):
    return rows(conn, "SELECT * FROM quiz_submissions WHERE owner=? AND id=?",
                (owner, attempt_id)).fetchone()


def quiz_attempt(conn, source_row):
    key = f"progress:{source_row['roadmap_id']}:{source_row['topic_id']}"
    record = conn.execute("SELECT value FROM records WHERE key=?", (key,)).fetchone()
    attempts = json.loads(record[0]).get(str(source_row["question"]), []) if record else []
    position = source_row["position"]
    if position < len(attempts) and attempts[position].get("attempt_id") == source_row["id"]:
        return attempts[position], position == len(attempts) - 1
    return None, False


def concept_record(conn, key):
    return rows(conn, """SELECT * FROM learner_memories
        WHERE owner=? AND roadmap_id=? AND diagnostic=? AND dimension=?""", key).fetchone()


def record(conn, memory_id, revision=None, owner=OWNER):
    row = rows(conn, "SELECT * FROM learner_memories WHERE owner=? AND id=?",
               (owner, memory_id)).fetchone()
    if revision is None or (row and row["revision"] == revision and row["status"] != "resolved"):
        return row


def suppression(conn, key):
    return conn.execute("""SELECT cutoff, suppressed FROM learner_memory_suppression
        WHERE owner=? AND roadmap_id=? AND diagnostic=? AND dimension=?""", key).fetchone()


def add_submission(conn, attempt_id, rid, tid, version, question, position, diagnostic, dimension, owner=OWNER):
    enabled, generation, _ = settings(conn, owner)
    cursor = conn.execute("""INSERT INTO quiz_submissions
        (owner, id, roadmap_id, topic_id, lesson_version, question, position, observed_at, generation, language)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (owner, attempt_id, rid, tid, version, question, position, now(), generation if enabled else None, language.get()))
    if enabled and diagnostic:
        key = (owner, rid, diagnostic, dimension)
        memory = concept_record(conn, key)
        conn.execute("""INSERT INTO learner_memory_pending
            (owner, submission_seq, diagnostic, dimension, expected_revision) VALUES (?, ?, ?, ?, ?)""",
            (owner, cursor.lastrowid, diagnostic, dimension, memory["revision"] if memory else None))


def unit_statement(diagnostic, lang):
    if diagnostic == "missing_unit":
        return "Đã bỏ sót đơn vị trong đáp án." if lang == "vi" else "Left units out of the answer."
    return "Đã dùng đơn vị không tương thích." if lang == "vi" else "Used incompatible units."


def refresh(conn, owner, memory_id, revision):
    count = conn.execute("""SELECT COUNT(*) FROM learner_memory_evidence
        WHERE owner=? AND memory_id=?""", (owner, memory_id)).fetchone()[0]
    status = "recurring" if count >= 2 else "tentative" if count else "resolved"
    updated = conn.execute("""UPDATE learner_memories SET status=?, revision=revision+1, updated_at=?
        WHERE owner=? AND id=? AND status!='confirmed' AND revision=?""", (status, now(), owner, memory_id, revision))
    if updated.rowcount != 1:
        raise RuntimeError("Memory changed while applying evidence")


def project(conn, observation, diagnostic, dimension, expected_revision=None, *, resume=False):
    owner, rid, seq = (observation[k] for k in ("owner", "roadmap_id", "seq"))
    key = (owner, rid, diagnostic, dimension)
    observes_error = diagnostic != "correct"
    rule = suppression(conn, key) if observes_error and not resume else None
    if rule and seq <= rule[0]:
        return
    target = concept_record(conn, key) if observes_error else None
    add_evidence = observes_error and not (rule and rule[1]) and not (target and target["status"] == "confirmed")

    previous = rows(conn, """SELECT m.id, m.revision, e.submission_seq FROM learner_memory_evidence e
        JOIN quiz_submissions q ON q.owner=e.owner AND q.seq=e.submission_seq
        JOIN learner_memories m ON m.owner=e.owner AND m.id=e.memory_id
        WHERE q.owner=? AND q.roadmap_id=? AND q.topic_id=? AND q.lesson_version=? AND q.question=?
        AND m.status!='confirmed'""", (owner, rid, *(observation[k] for k in ("topic_id", "lesson_version", "question")))).fetchall()
    if any(row["submission_seq"] >= seq for row in previous):
        return
    for row in previous:
        conn.execute("DELETE FROM learner_memory_evidence WHERE owner=? AND submission_seq=?",
                     (owner, row["submission_seq"]))

    changed = {row["id"]: row["revision"] for row in previous}
    if add_evidence:
        memory_id = target["id"] if target else uuid4().hex
        revision = expected_revision
        # Re-evaluate an older job against the current automatic revision only after the learner-edit check.
        if target and revision != target["revision"]:
            revision = target["revision"]
        if not target:
            revision = 0
            lang = observation["language"]
            at = now()
            conn.execute("""INSERT INTO learner_memories VALUES
                (?, ?, 'recurring_mistake', ?, ?, ?, ?, ?, 'tentative', 0, ?, ?)""",
                (owner, memory_id, unit_statement(diagnostic, lang), rid, diagnostic, dimension, lang, at, at))
        conn.execute("INSERT INTO learner_memory_evidence VALUES (?, ?, ?)", (owner, memory_id, seq))
        changed[memory_id] = revision
    for memory_id, revision in changed.items():
        refresh(conn, owner, memory_id, revision)


def apply_event(conn, event):
    enabled, generation, processed = settings(conn, event["owner"])
    if not enabled or event["generation"] != generation or event["seq"] <= processed:
        return
    project(conn, event, event["diagnostic"], event["dimension"], event["expected_revision"])
    conn.execute("UPDATE learner_memory_settings SET processed_through=? WHERE owner=?",
                 (event["seq"], event["owner"]))


def process_pending(db, limit=32):
    with db() as conn:
        for _ in range(limit):
            pending = conn.execute("SELECT 1 FROM learner_memory_pending WHERE owner=? LIMIT 1", (OWNER,)).fetchone()
            if not pending:
                return
            conn.execute("BEGIN IMMEDIATE")
            event = rows(conn, """SELECT q.*, p.diagnostic, p.dimension, p.expected_revision
                FROM learner_memory_pending p JOIN quiz_submissions q ON q.owner=p.owner AND q.seq=p.submission_seq
                WHERE p.owner=? ORDER BY p.submission_seq LIMIT 1""", (OWNER,)).fetchone()
            if not event:
                return
            try:
                apply_event(conn, event)
                conn.execute("DELETE FROM learner_memory_pending WHERE owner=? AND submission_seq=?",
                             (OWNER, event["seq"]))
                conn.commit()
            except Exception as exc:
                conn.rollback()
                conn.execute("""UPDATE learner_memory_pending SET failures=failures+1
                    WHERE owner=? AND submission_seq=?""", (OWNER, event["seq"]))
                conn.commit()
                logging.getLogger(__name__).warning("Learner memory processing failed (%s)", type(exc).__name__)
                return


def not_found():
    return HTTPException(404, tr("Không tìm thấy bộ nhớ này.", "Memory not found."))


def source_unavailable():
    return HTTPException(404, tr("Nguồn này không còn khả dụng hoặc đã thay đổi.", "This source is unavailable or has changed."))


def require_enabled(conn, owner=OWNER):
    if not settings(conn, owner)[0]:
        raise HTTPException(409, tr("Hãy bật lưu bộ nhớ học tập trước.", "Turn on learner memory first."))


def current(conn, memory_id, revision, owner):
    item = record(conn, memory_id, owner=owner)
    if not item:
        raise not_found()
    if item["revision"] != revision:
        raise HTTPException(409, tr("Bộ nhớ đã thay đổi. Hãy tải lại và thử lại.", "This memory changed. Refresh and try again."))
    return item


def create(conn, kind, statement, owner=OWNER):
    require_enabled(conn, owner)
    at = now()
    conn.execute("""INSERT INTO learner_memories
        (owner, id, kind, statement, language, status, revision, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 'confirmed', 1, ?, ?)""", (owner, uuid4().hex, kind, statement, language.get(), at, at))


def edit(conn, memory_id, revision, statement, owner=OWNER):
    current(conn, memory_id, revision, owner)
    conn.execute("""UPDATE learner_memories SET statement=?, language=?, status='confirmed',
        revision=revision+1, updated_at=? WHERE owner=? AND id=?""", (statement, language.get(), now(), owner, memory_id))


def cutoff(conn, owner):
    return conn.execute("SELECT COALESCE(MAX(seq), 0) FROM quiz_submissions WHERE owner=?", (owner,)).fetchone()[0]


def forget(conn, memory_id, revision, owner=OWNER):
    item = current(conn, memory_id, revision, owner)
    if item["diagnostic"]:
        key = (owner, item["roadmap_id"], item["diagnostic"], item["dimension"])
        conn.execute("INSERT OR REPLACE INTO learner_memory_suppression VALUES (?, ?, ?, ?, ?, 1)", (*key, cutoff(conn, owner)))
        conn.execute("""DELETE FROM learner_memory_pending WHERE owner=? AND diagnostic=? AND dimension=?
            AND submission_seq IN (SELECT seq FROM quiz_submissions WHERE owner=? AND roadmap_id=?)""",
            (owner, item["diagnostic"], item["dimension"], owner, item["roadmap_id"]))
    conn.execute("DELETE FROM learner_memory_evidence WHERE owner=? AND memory_id=?", (owner, memory_id))
    conn.execute("DELETE FROM learner_memories WHERE owner=? AND id=?", (owner, memory_id))


def reference(row):
    return dict(attempt_id=row["id"], **{key: row[key] for key in (
        "roadmap_id", "topic_id", "lesson_version", "question", "observed_at")})


def evidence(conn, memory_id, owner=OWNER):
    return rows(conn, """SELECT q.* FROM learner_memory_evidence e JOIN quiz_submissions q
        ON q.owner=e.owner AND q.seq=e.submission_seq
        WHERE e.owner=? AND e.memory_id=? ORDER BY q.seq""", (owner, memory_id))


def public_memory(conn, row, road_title):
    memory = {key: row[key] for key in row.keys() if key != "owner"}
    memory["scope"] = "roadmap" if row["roadmap_id"] else "learner"
    memory["confidence"] = {"tentative": "low", "recurring": "supported", "resolved": "none", "confirmed": "learner"}[row["status"]]
    if row["status"] != "confirmed":
        memory["statement"] = unit_statement(row["diagnostic"], language.get())
    memory["roadmap_title"] = road_title(row["roadmap_id"]) if row["roadmap_id"] else None
    memory["evidence"] = [reference(source_row) for source_row in evidence(conn, row["id"], row["owner"])]
    return memory


def list_memories(conn, road_title, owner=OWNER):
    memories = [public_memory(conn, row, road_title) for row in rows(
        conn, "SELECT * FROM learner_memories WHERE owner=? ORDER BY updated_at DESC, id", (owner,))]
    return dict(enabled=bool(settings(conn, owner)[0]), memories=memories)


def source_question(conn, row):
    key = f"lesson:{row['roadmap_id']}:{row['topic_id']}"
    record = conn.execute("SELECT value FROM records WHERE key=?", (key,)).fetchone()
    if record:
        lesson = json.loads(record[0])
        if lesson.get("version") == row["lesson_version"] and row["question"] < len(lesson["quiz"]):
            return lesson["quiz"][row["question"]]
    raise source_unavailable()


def evidence_detail(conn, memory_id, attempt_id, owner=OWNER):
    row = next((row for row in evidence(conn, memory_id, owner) if row["id"] == attempt_id), None)
    if not row:
        raise source_unavailable()
    question = source_question(conn, row)
    attempt, _ = quiz_attempt(conn, row)
    if not attempt:
        raise source_unavailable()
    return dict(reference(row), prompt=question["prompt"], **{k: attempt[k] for k in ("answer", "correct", "explanation")})


def eligible_key(conn, row, question, answer, generation):
    if row["generation"] != generation:
        return
    _, diagnostic, dimension = assess(question, answer)
    if diagnostic in ("missing_unit", "incompatible_unit"):
        key = (row["owner"], row["roadmap_id"], diagnostic, dimension)
        rule = suppression(conn, key)
        if rule and rule[1] and row["seq"] > rule[0]:
            return key


def mark_eligible(conn, rid, doc, progress, owner=OWNER):
    enabled, generation, _ = settings(conn, owner)
    if not enabled or not conn.execute("""SELECT 1 FROM learner_memory_suppression
        WHERE owner=? AND roadmap_id=? AND suppressed=1 LIMIT 1""", (owner, rid)).fetchone():
        return progress
    for question, attempts in progress.items():
        index = int(question)
        if index >= len(doc["quiz"]) or not attempts or not attempts[-1].get("attempt_id"):
            continue
        latest = attempts[-1]
        row = source(conn, latest["attempt_id"], owner)
        if row and row["lesson_version"] == doc["version"] and eligible_key(conn, row, doc["quiz"][index], latest["answer"], generation):
            latest["can_remember"] = True
    return progress


def resume(conn, attempt_id, owner=OWNER):
    require_enabled(conn, owner)
    row = source(conn, attempt_id, owner)
    if not row:
        raise source_unavailable()
    attempt, latest = quiz_attempt(conn, row)
    _, generation, _ = settings(conn, owner)
    key = eligible_key(conn, row, source_question(conn, row), attempt["answer"], generation) if latest else None
    if not key:
        raise HTTPException(409, tr("Không thể lưu lại từ lần làm này.", "This attempt can no longer be used to remember the pattern."))
    conn.execute("""UPDATE learner_memory_suppression SET suppressed=0, cutoff=?
        WHERE owner=? AND roadmap_id=? AND diagnostic=? AND dimension=?""", (cutoff(conn, owner), *key))
    project(conn, row, key[2], key[3], resume=True)
