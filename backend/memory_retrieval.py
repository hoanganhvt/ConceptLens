"""Versioned, owner-scoped vector retrieval for learner memories."""

from array import array
from contextlib import contextmanager
import logging
import math
import sqlite3
import sys
from time import monotonic
import unicodedata

from fastapi import HTTPException

from . import learner_memory
from .chat_state import OWNER, conflict
from .language import language, tr

log = logging.getLogger("uvicorn.error").getChild("memory_retrieval")
ELIGIBLE = "m.status IN ('confirmed','recurring')"


def migrate(conn):
    conn.execute("""CREATE TABLE learner_memory_vectors (
        owner TEXT NOT NULL, memory_id TEXT NOT NULL, revision INTEGER NOT NULL,
        encoder_id TEXT NOT NULL, dimension INTEGER NOT NULL, vector BLOB NOT NULL,
        PRIMARY KEY(owner, encoder_id, memory_id))""")
    conn.execute("""CREATE TABLE learner_memory_index (
        owner TEXT PRIMARY KEY, encoder_id TEXT NOT NULL)""")
    conn.execute("""CREATE TRIGGER learner_memory_vector_update
        AFTER UPDATE OF revision ON learner_memories WHEN OLD.revision <> NEW.revision
        BEGIN DELETE FROM learner_memory_vectors WHERE owner=OLD.owner AND memory_id=OLD.id; END""")
    conn.execute("""CREATE TRIGGER learner_memory_vector_delete AFTER DELETE ON learner_memories
        BEGIN DELETE FROM learner_memory_vectors WHERE owner=OLD.owner AND memory_id=OLD.id; END""")


def active_index(conn, owner=OWNER):
    indexed = conn.execute("SELECT encoder_id FROM learner_memory_index WHERE owner=?", (owner,)).fetchone()
    return indexed[0] if indexed else None


def encoder_status(conn, encoder):
    metadata = encoder.metadata
    if encoder.status != "ready" or not metadata:
        return encoder.status
    return "ready" if active_index(conn) == metadata["id"] else "building"


def active_sources(conn, row):
    sources, questions = [], set()
    for source in learner_memory.evidence(conn, row["id"], row["owner"]):
        if source["roadmap_id"] != row["roadmap_id"]:
            continue
        try:
            learner_memory.source_question(conn, source)
        except HTTPException:
            continue
        attempt, _ = learner_memory.quiz_attempt(conn, source)
        question = tuple(source[key] for key in ("topic_id", "lesson_version", "question"))
        if attempt and attempt.get("correct") is False and question not in questions:
            questions.add(question)
            sources.append(source["id"])
            if len(sources) == 2:
                break
    return sources


def provenance(conn, row):
    if not row:
        return
    if row["status"] == "confirmed":
        if (row["kind"] in ("goal", "preference") and row["roadmap_id"] is None
                or row["kind"] == "recurring_mistake" and row["roadmap_id"]):
            return {"source": "learner"}
    if row["status"] == "recurring" and row["kind"] == "recurring_mistake" and row["roadmap_id"]:
        sources = active_sources(conn, row)
        if len(sources) == 2:
            return {"source": "quiz", "attempt_ids": sources}


def storage(vector):
    values = array("f", vector)
    if sys.byteorder != "little":
        values.byteswap()
    return values.tobytes()


def unpack(blob):
    values = array("f")
    values.frombytes(blob)
    if sys.byteorder != "little":
        values.byteswap()
    return values


def normalized(values, dimension):
    if len(values) != dimension or not all(math.isfinite(value) for value in values):
        raise ValueError("Invalid vector")
    norm = math.sqrt(math.sumprod(values, values))
    if not math.isfinite(norm):
        raise ValueError("Invalid vector norm")
    return [value / norm for value in values] if norm else None


def unindexed(conn, metadata, limit):
    return learner_memory.rows(conn, f"""SELECT m.* FROM learner_memories m
        WHERE m.owner=? AND {ELIGIBLE}
        AND NOT EXISTS (SELECT 1 FROM learner_memory_vectors v
          WHERE v.owner=m.owner AND v.memory_id=m.id AND v.revision=m.revision
            AND v.encoder_id=? AND v.dimension=? AND length(v.vector) IN (0,?))
        ORDER BY m.id LIMIT ?""", (OWNER, metadata["id"], metadata["dimension"], metadata["dimension"] * 4, limit)).fetchall()


def indexed_text(row):
    return row["statement"] + (f'\nQuantity: {row["dimension"]}' if row["dimension"] else "")


def sync(db, encoder):
    with db() as conn:
        enabled, generation, _ = learner_memory.settings(conn)
    if not enabled:
        encoder.close()
        return
    encoder.start()
    metadata = encoder.metadata
    if not metadata or encoder.status != "ready":
        return
    with db() as conn:
        enabled, current_generation, _ = learner_memory.settings(conn)
        if not enabled or generation != current_generation:
            return
        pending = unindexed(conn, metadata, 8)
        if not pending and active_index(conn) == metadata["id"]:
            return
    vectors = (encoder.encode([indexed_text(row) for row in pending],
                              query=False, deadline=monotonic() + 10) if pending else [])
    if vectors is None or len(vectors) != len(pending):
        return
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        enabled, current_generation, _ = learner_memory.settings(conn)
        if not enabled or generation != current_generation:
            return
        for row, values in zip(pending, vectors):
            current = learner_memory.record(conn, row["id"], row["revision"])
            if current and current["status"] in ("confirmed", "recurring"):
                vector = normalized(values, metadata["dimension"])
                conn.execute("INSERT OR REPLACE INTO learner_memory_vectors VALUES (?,?,?,?,?,?)",
                             (OWNER, row["id"], row["revision"], metadata["id"], metadata["dimension"],
                              storage(vector) if vector else b""))
        if not unindexed(conn, metadata, 1):
            conn.execute("INSERT OR REPLACE INTO learner_memory_index VALUES (?,?)", (OWNER, metadata["id"]))
            conn.execute("DELETE FROM learner_memory_vectors WHERE owner=? AND encoder_id<>?",
                         (OWNER, metadata["id"]))


@contextmanager
def short_read(db, deadline):
    with db() as conn:
        conn.execute("PRAGMA busy_timeout=25")
        conn.set_progress_handler(lambda: int(monotonic() >= deadline), 1000)
        conn.execute("BEGIN")
        yield conn


def candidates(conn, metadata, rid):
    return learner_memory.rows(conn, f"""SELECT m.*, v.vector FROM learner_memories m
        JOIN learner_memory_vectors v
          ON v.owner=m.owner AND v.memory_id=m.id AND v.revision=m.revision
        WHERE m.owner=? AND (m.roadmap_id IS NULL OR m.roadmap_id=?) AND {ELIGIBLE}
          AND v.encoder_id=? AND v.dimension=? AND length(v.vector)=?""",
        (OWNER, rid, metadata["id"], metadata["dimension"], metadata["dimension"] * 4))


def resolve(conn, vector, metadata, rid, deadline):
    ranked = []
    for row in candidates(conn, metadata, rid):
        if monotonic() >= deadline:
            raise TimeoutError
        source = provenance(conn, row)
        if not source:
            continue
        similarity = math.sumprod(vector, unpack(row["vector"]))
        if math.isfinite(similarity) and similarity >= metadata["threshold"]:
            ranked.append((similarity, row["status"] == "confirmed", row["updated_at"], row["id"], row, source))
    ranked.sort(reverse=True)
    selected, seen = [], set()
    for _, _, _, _, row, source in ranked:
        key = " ".join(unicodedata.normalize("NFKC", indexed_text(row)).casefold().split())
        if key in seen:
            continue
        seen.add(key)
        statement = (row["statement"] if source["source"] == "learner"
                     else learner_memory.unit_statement(row["diagnostic"], language.get()))
        selected.append({"id": row["id"], "revision": row["revision"], "statement": statement,
                         "kind": row["kind"], "scope": "roadmap" if row["roadmap_id"] else "learner",
                         "provenance": source})
        if len(selected) == 3:
            break
    return selected


def retrieve(db, encoder, rid, topic, note, question):
    start = monotonic()
    deadline = start + 0.200
    metadata = encoder.metadata
    if encoder.status != "ready" or not metadata:
        log.info("memory_retrieval status=encoder_%s count=0 elapsed_ms=0", encoder.status)
        return None, []
    status, selected = "changed", []
    try:
        with short_read(db, deadline) as conn:
            enabled, generation, _ = learner_memory.settings(conn)
            if not enabled:
                status = "paused"
                return None, []
            if active_index(conn) != metadata["id"]:
                status = "building"
                return None, []
        query = "\n".join((question[:1000], topic["title"][:256], (note or {}).get("quote", "")[:256]))
        vectors = encoder.encode([query], query=True, deadline=deadline)
        if monotonic() >= deadline:
            raise TimeoutError
        if not vectors:
            status = "unavailable"
            return None, []
        vector = normalized(vectors[0], metadata["dimension"])
        if vector is None:
            status = "no_match"
            return generation, []
        with short_read(db, deadline) as conn:
            enabled, current_generation, _ = learner_memory.settings(conn)
            if not enabled or generation != current_generation or active_index(conn) != metadata["id"]:
                return None, []
            selected = resolve(conn, vector, metadata, rid, deadline)
        if monotonic() >= deadline:
            raise TimeoutError
        status = "matched" if selected else "no_match"
        return generation, selected
    except (sqlite3.Error, TimeoutError, ValueError):
        selected = []
        status = "timeout" if monotonic() >= deadline else "error"
        return None, []
    finally:
        log.info("memory_retrieval status=%s count=%d elapsed_ms=%.1f",
                 status, len(selected), (monotonic() - start) * 1000)


def validate(conn, rid, generation, references, *, required):
    if not references:
        return []
    enabled, current_generation, _ = learner_memory.settings(conn)
    valid = []
    if enabled and generation == current_generation:
        for ref in references:
            row = learner_memory.record(conn, ref["id"], ref["revision"])
            if row and row["roadmap_id"] in (None, rid) and provenance(conn, row):
                valid.append(ref)
    if required and len(valid) != len(references):
        raise changed()
    return valid


def changed():
    return conflict(tr("Không thể xác minh bộ nhớ hiện tại. Hãy gửi lại câu hỏi.",
                       "Learner memory could not be verified. Please retry your question."))
