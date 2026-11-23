"""SQLite state for append-only tutor threads."""

import hashlib
import json
import time
from uuid import uuid4

from fastapi import HTTPException

from .language import tr

OWNER = "local"
LEASE_SECONDS = 300


def migrate(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS tutor_leases (
        owner TEXT NOT NULL, branch TEXT NOT NULL, token TEXT NOT NULL,
        request_id TEXT NOT NULL, revision INTEGER NOT NULL, expires REAL NOT NULL,
        PRIMARY KEY (owner, branch))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS tutor_requests (
        owner TEXT NOT NULL, branch TEXT NOT NULL, request_id TEXT NOT NULL,
        fingerprint TEXT NOT NULL, committed_revision INTEGER NOT NULL,
        PRIMARY KEY (owner, branch, request_id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS tutor_summaries (
        owner TEXT NOT NULL, roadmap TEXT NOT NULL, topic TEXT NOT NULL,
        lesson_version TEXT NOT NULL, branch TEXT NOT NULL, format INTEGER NOT NULL,
        covered INTEGER NOT NULL, content TEXT NOT NULL,
        PRIMARY KEY (owner, roadmap, topic, lesson_version, branch, format))""")


def transcript(conn, branch):
    row = conn.execute("SELECT value FROM records WHERE key=?", (branch,)).fetchone()
    return json.loads(row[0]) if row else []


def conflict(message):
    return HTTPException(409, message, headers={"Retry-After": "1"})


class Send:
    def __init__(self, db, branch, request_id, text, search):
        self.db = db
        self.branch = (OWNER, branch)
        self.request_id = str(request_id or uuid4())
        self.token = uuid4().hex
        self.fingerprint = hashlib.sha256(json.dumps([text, search]).encode()).hexdigest()

    def reserve(self):
        with self.db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            history = transcript(conn, self.branch[1])
            prior = conn.execute("""SELECT fingerprint FROM tutor_requests
                WHERE owner=? AND branch=? AND request_id=?""", (*self.branch, self.request_id)).fetchone()
            if prior:
                if prior[0] != self.fingerprint:
                    raise HTTPException(409, tr("Mã yêu cầu đã được dùng cho câu hỏi khác.",
                                                "This request ID already belongs to a different question."))
                return history, True
            now = time.time()
            active = conn.execute("""SELECT request_id FROM tutor_leases
                WHERE owner=? AND branch=? AND expires>?""", (*self.branch, now)).fetchone()
            if active:
                if active[0] == self.request_id:
                    raise conflict(tr("Câu hỏi này đang được xử lý. Hãy thử lại.",
                                      "This question is already being processed. Please retry."))
                raise conflict(tr("Một câu hỏi khác đang được xử lý trong cuộc trò chuyện này. Hãy thử lại.",
                                  "Another question is being processed in this conversation. Please retry."))
            conn.execute("INSERT OR REPLACE INTO tutor_leases VALUES (?,?,?,?,?,?)",
                         (*self.branch, self.token, self.request_id, len(history), now + LEASE_SECONDS))
            return history, False

    def renew(self):
        with self.db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            now = time.time()
            changed = conn.execute("""UPDATE tutor_leases SET expires=?
                WHERE owner=? AND branch=? AND token=? AND expires>?""",
                (now + LEASE_SECONDS, *self.branch, self.token, now))
            if not changed.rowcount:
                self.expired()

    def expired(self):
        raise conflict(tr("Yêu cầu đã hết hạn. Hãy gửi lại câu hỏi.",
                          "The request expired. Please send your question again."))

    def commit(self, user, reply, summary=None):
        with self.db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            active = conn.execute("""SELECT revision FROM tutor_leases
                WHERE owner=? AND branch=? AND token=? AND expires>?""",
                (*self.branch, self.token, time.time())).fetchone()
            history = transcript(conn, self.branch[1])
            if not active or active[0] != len(history):
                self.expired()
            history.extend((user, reply))
            conn.execute("INSERT OR REPLACE INTO records VALUES (?,?)",
                         (self.branch[1], json.dumps(history, ensure_ascii=False)))
            conn.execute("INSERT INTO tutor_requests VALUES (?,?,?,?,?)",
                         (*self.branch, self.request_id, self.fingerprint, len(history)))
            if summary:
                key, covered, content = summary
                conn.execute("INSERT OR REPLACE INTO tutor_summaries VALUES (?,?,?,?,?,?,?,?)",
                             (*key, covered, json.dumps(content, ensure_ascii=False)))
            self.release(conn)
            return history

    def release(self, conn=None):
        sql = "DELETE FROM tutor_leases WHERE owner=? AND branch=? AND token=?"
        if conn is not None:
            conn.execute(sql, (*self.branch, self.token))
        else:
            with self.db() as connection:
                connection.execute(sql, (*self.branch, self.token))
