from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path
from threading import Lock

logger = logging.getLogger(__name__)

_SNAP_CLICK: float = 0.25
_SNAP_ORIGIN: float = 1.0

_CREATE_CLICK_EVENTS = """
CREATE TABLE IF NOT EXISTS click_events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        INTEGER NOT NULL,
    click_lat REAL    NOT NULL,
    click_lon REAL    NOT NULL
)
"""

_CREATE_SESSION_EVENTS = """
CREATE TABLE IF NOT EXISTS session_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           INTEGER NOT NULL,
    user_country TEXT,
    user_lat     REAL,
    user_lon     REAL
)
"""

_CREATE_CHAT_MESSAGES = """
CREATE TABLE IF NOT EXISTS chat_messages (
    message_id        TEXT    PRIMARY KEY,
    session_id        TEXT    NOT NULL,
    ts                INTEGER NOT NULL,
    question          TEXT    NOT NULL,
    answer            TEXT,
    step_count        INTEGER,
    tools_called      TEXT,
    tool_calls_detail TEXT,
    tier              TEXT,
    feedback          TEXT,
    feedback_ts       INTEGER,
    feedback_status   TEXT,
    opt_out           INTEGER NOT NULL DEFAULT 0,
    map_lat           REAL,
    map_lon           REAL,
    map_label         TEXT,
    total_ms          INTEGER,
    steps_timing      TEXT,
    model             TEXT,
    rejected_tiers    TEXT,
    model_override    TEXT,
    error             TEXT
)
"""

def snap(value: float, resolution: float) -> float:
    return round(value / resolution) * resolution


class AnalyticsDB:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._lock = Lock()

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(_CREATE_CLICK_EVENTS)
            conn.execute(_CREATE_SESSION_EVENTS)
            conn.execute(_CREATE_CHAT_MESSAGES)
            conn.commit()
            self._conn = conn
        return self._conn

    def check_schema(self) -> None:
        """Call at startup. Logs an error and raises if required columns are missing."""
        required = {"message_id", "session_id", "tool_calls_detail", "tier", "total_ms", "steps_timing", "model", "rejected_tiers", "model_override", "error"}
        try:
            with self._lock:
                conn = self._connect()
                cols = {row[1] for row in conn.execute("PRAGMA table_info(chat_messages)").fetchall()}
            missing = required - cols
            if missing:
                raise RuntimeError(
                    f"Analytics DB schema is stale — missing columns: {sorted(missing)}. "
                    f"Wipe the DB and restart: "
                    f"sqlite3 {self._db_path} "
                    f"\"DROP TABLE IF EXISTS chat_messages; "
                    f"DROP TABLE IF EXISTS chat_sessions; "
                    f"DROP TABLE IF EXISTS click_events; "
                    f"DROP TABLE IF EXISTS session_events;\""
                )
        except RuntimeError:
            raise
        except Exception:
            logger.exception("Failed to check analytics DB schema")

    def record_click(self, click_lat: float, click_lon: float) -> None:
        lat = snap(click_lat, _SNAP_CLICK)
        lon = snap(click_lon, _SNAP_CLICK)
        ts = int(time.time())
        try:
            with self._lock:
                conn = self._connect()
                conn.execute(
                    "INSERT INTO click_events (ts, click_lat, click_lon) VALUES (?, ?, ?)",
                    (ts, lat, lon),
                )
                conn.commit()
        except Exception:
            logger.exception("Failed to record click event")

    def record_session(
        self,
        user_country: str | None,
        user_lat: float | None,
        user_lon: float | None,
    ) -> None:
        lat = snap(user_lat, _SNAP_ORIGIN) if user_lat is not None else None
        lon = snap(user_lon, _SNAP_ORIGIN) if user_lon is not None else None
        ts = int(time.time())
        try:
            with self._lock:
                conn = self._connect()
                conn.execute(
                    "INSERT INTO session_events (ts, user_country, user_lat, user_lon) VALUES (?, ?, ?, ?)",
                    (ts, user_country, lat, lon),
                )
                conn.commit()
        except Exception:
            logger.exception("Failed to record session event")

    def get_click_aggregates(self) -> list[dict]:
        try:
            with self._lock:
                conn = self._connect()
                rows = conn.execute(
                    "SELECT click_lat, click_lon, COUNT(*) FROM click_events"
                    " GROUP BY click_lat, click_lon"
                ).fetchall()
            return [{"lat": r[0], "lon": r[1], "count": r[2]} for r in rows]
        except Exception:
            logger.exception("Failed to query click aggregates")
            return []

    def get_session_aggregates(self) -> list[dict]:
        try:
            with self._lock:
                conn = self._connect()
                rows = conn.execute(
                    "SELECT user_country, user_lat, user_lon, COUNT(*) FROM session_events"
                    " GROUP BY user_country, user_lat, user_lon"
                ).fetchall()
            return [
                {"country": r[0], "lat": r[1], "lon": r[2], "count": r[3]}
                for r in rows
            ]
        except Exception:
            logger.exception("Failed to query session aggregates")
            return []

    def get_last_event_ts(self) -> int | None:
        """Return the Unix timestamp of the most recent click or session event."""
        try:
            with self._lock:
                conn = self._connect()
                r1 = conn.execute("SELECT MAX(ts) FROM click_events").fetchone()[0]
                r2 = conn.execute("SELECT MAX(ts) FROM session_events").fetchone()[0]
            candidates = [t for t in (r1, r2) if t is not None]
            return max(candidates) if candidates else None
        except Exception:
            logger.exception("Failed to query last event ts")
            return None

    # ------------------------------------------------------------------
    # Chat sessions
    # ------------------------------------------------------------------

    def record_chat_message(
        self,
        message_id: str,
        session_id: str,
        question: str,
        answer: str | None,
        step_count: int,
        tools_called: list[str],
        tool_calls_detail: list[dict] | None = None,
        tier: str | None = None,
        opt_out: bool = False,
        map_lat: float | None = None,
        map_lon: float | None = None,
        map_label: str | None = None,
        total_ms: int | None = None,
        steps_timing: list[dict] | None = None,
        model: str | None = None,
        rejected_tiers: list[str] | None = None,
        model_override: str | None = None,
        error: str | None = None,
    ) -> None:
        import json as _json
        ts = int(time.time())
        try:
            with self._lock:
                conn = self._connect()
                conn.execute(
                    """INSERT OR REPLACE INTO chat_messages
                       (message_id, session_id, ts, question, answer, step_count, tools_called,
                        tool_calls_detail, tier, opt_out, map_lat, map_lon, map_label,
                        total_ms, steps_timing, model, rejected_tiers, model_override, error,
                        feedback_status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        message_id, session_id, ts, question, answer, step_count,
                        _json.dumps(tools_called),
                        _json.dumps(tool_calls_detail) if tool_calls_detail is not None else None,
                        tier, int(opt_out),
                        map_lat, map_lon, map_label,
                        total_ms,
                        _json.dumps(steps_timing) if steps_timing is not None else None,
                        model,
                        _json.dumps(rejected_tiers) if rejected_tiers is not None else None,
                        model_override,
                        error,
                        "new" if error else None,
                    ),
                )
                conn.commit()
        except Exception:
            logger.exception("Failed to record chat message")

    def record_chat_feedback(self, message_id: str, feedback: str | None) -> None:
        """
        feedback: 'good', 'bad', or None (clears feedback).
        When feedback='bad', feedback_status is set to 'new'.
        Otherwise feedback_status is cleared.
        """
        ts = int(time.time()) if feedback else None
        status = "new" if feedback == "bad" else None
        try:
            with self._lock:
                conn = self._connect()
                conn.execute(
                    "UPDATE chat_messages SET feedback=?, feedback_ts=?, feedback_status=? WHERE message_id=?",
                    (feedback, ts, status, message_id),
                )
                conn.commit()
        except Exception:
            logger.exception("Failed to record chat feedback")

    def mark_bad_answer_reviewed(self, message_id: str) -> None:
        try:
            with self._lock:
                conn = self._connect()
                conn.execute(
                    "UPDATE chat_messages SET feedback_status='reviewed' WHERE message_id=? AND feedback='bad'",
                    (message_id,),
                )
                conn.commit()
        except Exception:
            logger.exception("Failed to mark bad answer as reviewed")

    def get_chat_messages(
        self,
        limit: int = 50,
        offset: int = 0,
        feedback: str | None = None,
    ) -> list[dict]:
        import json as _json
        try:
            with self._lock:
                conn = self._connect()
                cols = (
                    "message_id, session_id, ts, question, answer, step_count, tools_called, "
                    "tool_calls_detail, tier, feedback, feedback_status, total_ms, steps_timing, "
                    "model, rejected_tiers, model_override, error"
                )
                if feedback is not None:
                    rows = conn.execute(
                        f"SELECT {cols} FROM chat_messages"
                        " WHERE feedback=? ORDER BY ts DESC LIMIT ? OFFSET ?",
                        (feedback, limit, offset),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        f"SELECT {cols} FROM chat_messages"
                        " ORDER BY ts DESC LIMIT ? OFFSET ?",
                        (limit, offset),
                    ).fetchall()
            return [
                {
                    "message_id": r[0], "session_id": r[1], "ts": r[2], "question": r[3],
                    "answer_excerpt": (r[4] or "")[:200],
                    "step_count": r[5],
                    "tools_called": _json.loads(r[6]) if r[6] else [],
                    "tool_calls_detail": _json.loads(r[7]) if r[7] else [],
                    "tier": r[8],
                    "feedback": r[9], "feedback_status": r[10],
                    "total_ms": r[11],
                    "steps_timing": _json.loads(r[12]) if r[12] else [],
                    "model": r[13],
                    "rejected_tiers": _json.loads(r[14]) if r[14] else [],
                    "model_override": r[15],
                    "error": r[16],
                }
                for r in rows
            ]
        except Exception:
            logger.exception("Failed to query chat messages")
            return []

    def get_chat_bad_answers(self, limit: int = 50) -> list[dict]:
        """Return messages needing review: bad feedback or errors, with feedback_status='new'."""
        import json as _json
        try:
            with self._lock:
                conn = self._connect()
                cols = (
                    "message_id, session_id, ts, question, answer, step_count, tools_called, "
                    "tool_calls_detail, tier, feedback, feedback_status, total_ms, steps_timing, "
                    "model, rejected_tiers, model_override, error"
                )
                rows = conn.execute(
                    f"SELECT {cols} FROM chat_messages"
                    " WHERE feedback_status='new' ORDER BY ts DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [
                {
                    "message_id": r[0], "session_id": r[1], "ts": r[2], "question": r[3],
                    "answer_excerpt": (r[4] or "")[:200],
                    "step_count": r[5],
                    "tools_called": _json.loads(r[6]) if r[6] else [],
                    "tool_calls_detail": _json.loads(r[7]) if r[7] else [],
                    "tier": r[8],
                    "feedback": r[9], "feedback_status": r[10],
                    "total_ms": r[11],
                    "steps_timing": _json.loads(r[12]) if r[12] else [],
                    "model": r[13],
                    "rejected_tiers": _json.loads(r[14]) if r[14] else [],
                    "model_override": r[15],
                    "error": r[16],
                }
                for r in rows
            ]
        except Exception:
            logger.exception("Failed to query bad answers")
            return []

    def get_chat_stats(self) -> dict:
        try:
            with self._lock:
                conn = self._connect()
                total_messages = conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0]
                total_sessions = conn.execute("SELECT COUNT(DISTINCT session_id) FROM chat_messages").fetchone()[0]
                good = conn.execute("SELECT COUNT(*) FROM chat_messages WHERE feedback='good'").fetchone()[0]
                bad  = conn.execute("SELECT COUNT(*) FROM chat_messages WHERE feedback='bad'").fetchone()[0]
                new_bad = conn.execute(
                    "SELECT COUNT(*) FROM chat_messages WHERE feedback_status='new'"
                ).fetchone()[0]
                avg_steps = conn.execute("SELECT AVG(step_count) FROM chat_messages").fetchone()[0]
                timing_rows = conn.execute(
                    "SELECT total_ms FROM chat_messages WHERE total_ms IS NOT NULL ORDER BY total_ms"
                ).fetchall()

            avg_resp_ms: float | None = None
            p95_resp_ms: int | None = None
            if timing_rows:
                values = [r[0] for r in timing_rows]
                avg_resp_ms = round(sum(values) / len(values))
                p95_idx = max(0, int(len(values) * 0.95) - 1)
                p95_resp_ms = values[p95_idx]

            avg_msg_per_session = round(total_messages / total_sessions, 1) if total_sessions else None

            return {
                "total_messages": total_messages,
                "total_sessions": total_sessions,
                "avg_messages_per_session": avg_msg_per_session,
                "feedback_good": good,
                "feedback_bad": bad,
                "bad_answers_unreviewed": new_bad,
                "avg_step_count": round(avg_steps, 2) if avg_steps else None,
                "avg_resp_ms": avg_resp_ms,
                "p95_resp_ms": p95_resp_ms,
            }
        except Exception:
            logger.exception("Failed to query chat stats")
            return {}


class IPBlocklist:
    """Loads a plaintext file of IPs (one per line, # comments allowed) once at startup."""

    def __init__(self, path: Path) -> None:
        self._ips: frozenset[str] = frozenset()
        try:
            if path.exists():
                self._ips = frozenset(
                    line.strip()
                    for line in path.read_text().splitlines()
                    if line.strip() and not line.startswith("#")
                )
        except Exception:
            logger.exception("Failed to load IP blocklist from %s", path)

    def __len__(self) -> int:
        return len(self._ips)

    def is_blocked(self, ip: str) -> bool:
        return ip in self._ips
