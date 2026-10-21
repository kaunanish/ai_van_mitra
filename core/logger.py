"""
PART B, step 9: every interaction is logged to a local SQLite file (data/van_mitra.sqlite3).
This powers the admin page: visitors per day, top questions, and - most useful for the
forest office - the questions Van Mitra could NOT answer, so new content can be added.
"""
import json
import sqlite3
import threading
import time
from collections import Counter

import config

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS interactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  day TEXT NOT NULL,
  source TEXT,          -- voice | text
  transcript TEXT,
  route TEXT,           -- rule | pinned | rag | fallback | not_heard | error
  answer TEXT,
  chunk_ids TEXT,
  top_score REAL,
  gate_passed INTEGER,
  llm_mode TEXT,
  stt_ms INTEGER, retrieval_ms INTEGER, llm_ms INTEGER, tts_ms INTEGER, total_ms INTEGER
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  day TEXT NOT NULL,
  kind TEXT NOT NULL    -- visitor (presence started) | greeting
);
"""


def _conn():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(config.DB_PATH, timeout=5)
    c.row_factory = sqlite3.Row
    return c


def init():
    if not config.ENABLE_LOGGING:
        return
    with _lock, _conn() as c:
        c.executescript(SCHEMA)


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S"), time.strftime("%Y-%m-%d")


def log_interaction(source, transcript, route, answer, chunk_ids=None, top_score=None, gate_passed=None,
                    llm_mode=None, t=None):
    if not config.ENABLE_LOGGING:
        return
    t = t or {}
    ts, day = _now()
    with _lock, _conn() as c:
        c.execute("""INSERT INTO interactions (ts, day, source, transcript, route, answer, chunk_ids, top_score,
                     gate_passed, llm_mode, stt_ms, retrieval_ms, llm_ms, tts_ms, total_ms)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (ts, day, source, transcript, route, answer, json.dumps(chunk_ids or []), top_score,
                   None if gate_passed is None else int(gate_passed), llm_mode,
                   t.get("stt_ms"), t.get("retrieval_ms"), t.get("llm_ms"), t.get("tts_ms"), t.get("total_ms")))


def log_event(kind):
    if not config.ENABLE_LOGGING:
        return
    ts, day = _now()
    with _lock, _conn() as c:
        c.execute("INSERT INTO events (ts, day, kind) VALUES (?,?,?)", (ts, day, kind))


def stats():
    with _lock, _conn() as c:
        today = time.strftime("%Y-%m-%d")
        q = lambda sql, *a: c.execute(sql, a).fetchall()  # noqa: E731
        total = q("SELECT COUNT(*) n FROM interactions")[0]["n"]
        by_route = {r["route"]: r["n"] for r in q("SELECT route, COUNT(*) n FROM interactions GROUP BY route")}
        today_q = q("SELECT COUNT(*) n FROM interactions WHERE day=?", today)[0]["n"]
        visitors_today = q("SELECT COUNT(*) n FROM events WHERE kind='visitor' AND day=?", today)[0]["n"]
        per_day = q("""SELECT d.day, IFNULL(v.n,0) visitors, IFNULL(i.n,0) questions FROM
                       (SELECT day FROM events UNION SELECT day FROM interactions) d
                       LEFT JOIN (SELECT day, COUNT(*) n FROM events WHERE kind='visitor' GROUP BY day) v ON v.day=d.day
                       LEFT JOIN (SELECT day, COUNT(*) n FROM interactions GROUP BY day) i ON i.day=d.day
                       ORDER BY d.day DESC LIMIT 14""")
        answered = q("SELECT transcript FROM interactions WHERE route IN ('rag','pinned') AND transcript != ''")
        top = Counter(r["transcript"].strip().rstrip("?.!").lower() for r in answered).most_common(10)
        unanswered = q("""SELECT ts, transcript FROM interactions WHERE route='fallback'
                          ORDER BY id DESC LIMIT 30""")
        lat = q("SELECT AVG(total_ms) a, AVG(stt_ms) s, AVG(llm_ms) l FROM interactions WHERE route='rag'")[0]
        recent = q("SELECT ts, source, transcript, route, answer, total_ms FROM interactions ORDER BY id DESC LIMIT 25")
    return {
        "total": total, "today": today_q, "visitors_today": visitors_today, "by_route": by_route,
        "per_day": [dict(r) for r in per_day], "top": top,
        "unanswered": [dict(r) for r in unanswered], "recent": [dict(r) for r in recent],
        "avg_total_ms": int(lat["a"] or 0), "avg_stt_ms": int(lat["s"] or 0), "avg_llm_ms": int(lat["l"] or 0),
    }
