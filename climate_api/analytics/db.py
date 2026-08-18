from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path
from threading import Lock

logger = logging.getLogger(__name__)

_SNAP_CLICK: float = 0.25
_SNAP_ORIGIN: float = 1.0

# Tiers that answer from stored text instead of calling a model. They report the
# fixed think-time they were streamed with rather than a measured one, so a
# latency average that includes them tracks how often the fast paths hit, not
# how long an answer takes. Response-time stats are reported both ways.
FIXED_LATENCY_TIERS = frozenset({"canned", "templated"})


def _mean(values: list[int]) -> float | None:
    """Mean rounded for display; None when there is nothing to average."""
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _latency_summary(values: list[int]) -> tuple[int | None, int | None]:
    """(mean, p95) over an already-sorted list of durations; (None, None) if empty."""
    if not values:
        return None, None
    mean = round(sum(values) / len(values))
    p95_idx = max(0, int(len(values) * 0.95) - 1)
    return mean, values[p95_idx]

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
    message_id            TEXT    PRIMARY KEY,
    session_id            TEXT    NOT NULL,
    ts                    INTEGER NOT NULL,
    question              TEXT    NOT NULL,
    answer                TEXT,
    step_count            INTEGER,
    tools_called          TEXT,
    tool_calls_detail     TEXT,
    tier                  TEXT,
    feedback              TEXT,
    feedback_ts           INTEGER,
    feedback_status       TEXT,
    -- Set when the browser has analytics disabled (?analytics=off): the row is
    -- kept and stays readable in /admin, but every aggregate skips it. This is
    -- a "do not count this" flag, not a "do not store this" one — a privacy
    -- opt-out that promises the question is never written needs its own field.
    opt_out               INTEGER NOT NULL DEFAULT 0,
    map_lat               REAL,
    map_lon               REAL,
    map_label             TEXT,
    total_ms              INTEGER,
    steps_timing          TEXT,
    model                 TEXT,
    rejected_tiers        TEXT,
    model_override        TEXT,
    error                 TEXT,
    question_id           TEXT,
    parent_question_id    TEXT,
    question_tree_version TEXT
)
"""

# Columns added in later migrations — applied via ALTER TABLE to existing DBs.
_OPTIONAL_MIGRATIONS = [
    "ALTER TABLE chat_messages ADD COLUMN question_id TEXT",
    "ALTER TABLE chat_messages ADD COLUMN parent_question_id TEXT",
    "ALTER TABLE chat_messages ADD COLUMN question_tree_version TEXT",
]


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
        required = {
            "message_id",
            "session_id",
            "tool_calls_detail",
            "tier",
            "total_ms",
            "steps_timing",
            "model",
            "rejected_tiers",
            "model_override",
            "error",
        }
        try:
            with self._lock:
                conn = self._connect()
                cols = {
                    row[1]
                    for row in conn.execute(
                        "PRAGMA table_info(chat_messages)"
                    ).fetchall()
                }
            missing = required - cols
            if missing:
                raise RuntimeError(
                    f"Analytics DB schema is stale — missing columns: {sorted(missing)}. "
                    f"Wipe the DB and restart: "
                    f"sqlite3 {self._db_path} "
                    f'"DROP TABLE IF EXISTS chat_messages; '
                    f"DROP TABLE IF EXISTS chat_sessions; "
                    f"DROP TABLE IF EXISTS click_events; "
                    f'DROP TABLE IF EXISTS session_events;"'
                )
            # Apply optional migrations for columns added after initial schema creation.
            with self._lock:
                conn = self._connect()
                for stmt in _OPTIONAL_MIGRATIONS:
                    try:
                        conn.execute(stmt)
                        conn.commit()
                    except Exception:
                        pass  # column already exists
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
                {"country": r[0], "lat": r[1], "lon": r[2], "count": r[3]} for r in rows
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
        question_id: str | None = None,
        parent_question_id: str | None = None,
        question_tree_version: str | None = None,
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
                        feedback_status, question_id, parent_question_id, question_tree_version)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        message_id,
                        session_id,
                        ts,
                        question,
                        answer,
                        step_count,
                        _json.dumps(tools_called),
                        (
                            _json.dumps(tool_calls_detail)
                            if tool_calls_detail is not None
                            else None
                        ),
                        tier,
                        int(opt_out),
                        map_lat,
                        map_lon,
                        map_label,
                        total_ms,
                        _json.dumps(steps_timing) if steps_timing is not None else None,
                        model,
                        (
                            _json.dumps(rejected_tiers)
                            if rejected_tiers is not None
                            else None
                        ),
                        model_override,
                        error,
                        "new" if error else None,
                        question_id,
                        parent_question_id,
                        question_tree_version,
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
                    "UPDATE chat_messages SET feedback_status='reviewed' WHERE message_id=?",
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
        """Recent messages, opted-out ones included and marked as such.

        This is the transcript view rather than a report: an opted-out message
        is still worth reading back when checking how the assistant answered.
        Every aggregate below drops those rows instead.
        """
        import json as _json

        try:
            with self._lock:
                conn = self._connect()
                cols = (
                    "message_id, session_id, ts, question, answer, step_count, tools_called, "
                    "tool_calls_detail, tier, feedback, feedback_status, total_ms, steps_timing, "
                    "model, rejected_tiers, model_override, error, "
                    "question_id, parent_question_id, question_tree_version, opt_out"
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
                    "message_id": r[0],
                    "session_id": r[1],
                    "ts": r[2],
                    "question": r[3],
                    "answer": r[4] or "",
                    "step_count": r[5],
                    "tools_called": _json.loads(r[6]) if r[6] else [],
                    "tool_calls_detail": _json.loads(r[7]) if r[7] else [],
                    "tier": r[8],
                    "feedback": r[9],
                    "feedback_status": r[10],
                    "total_ms": r[11],
                    "steps_timing": _json.loads(r[12]) if r[12] else [],
                    "model": r[13],
                    "rejected_tiers": _json.loads(r[14]) if r[14] else [],
                    "model_override": r[15],
                    "error": r[16],
                    "question_id": r[17],
                    "parent_question_id": r[18],
                    "question_tree_version": r[19],
                    "opt_out": bool(r[20]),
                }
                for r in rows
            ]
        except Exception:
            logger.exception("Failed to query chat messages")
            return []

    def get_chat_bad_answers(self, limit: int = 50) -> list[dict]:
        """Messages needing review: bad feedback or errors, with feedback_status='new'.

        Opted-out rows are left out — a failure hit while testing is already
        known about, and queueing it would bury the reports from real users.
        """
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
                    " WHERE feedback_status='new' AND opt_out=0 ORDER BY ts DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [
                {
                    "message_id": r[0],
                    "session_id": r[1],
                    "ts": r[2],
                    "question": r[3],
                    "answer": r[4] or "",
                    "step_count": r[5],
                    "tools_called": _json.loads(r[6]) if r[6] else [],
                    "tool_calls_detail": _json.loads(r[7]) if r[7] else [],
                    "tier": r[8],
                    "feedback": r[9],
                    "feedback_status": r[10],
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
        """Usage totals over real traffic only — opted-out rows are excluded."""
        try:
            with self._lock:
                conn = self._connect()
                total_messages = conn.execute(
                    "SELECT COUNT(*) FROM chat_messages WHERE opt_out=0"
                ).fetchone()[0]
                total_sessions = conn.execute(
                    "SELECT COUNT(DISTINCT session_id) FROM chat_messages WHERE opt_out=0"
                ).fetchone()[0]
                good = conn.execute(
                    "SELECT COUNT(*) FROM chat_messages WHERE feedback='good' AND opt_out=0"
                ).fetchone()[0]
                bad = conn.execute(
                    "SELECT COUNT(*) FROM chat_messages WHERE feedback='bad' AND opt_out=0"
                ).fetchone()[0]
                new_bad = conn.execute(
                    "SELECT COUNT(*) FROM chat_messages WHERE feedback_status='new' AND opt_out=0"
                ).fetchone()[0]
                step_rows = conn.execute(
                    "SELECT step_count, tier FROM chat_messages"
                    " WHERE step_count IS NOT NULL AND opt_out=0"
                ).fetchall()
                timing_rows = conn.execute(
                    "SELECT total_ms, tier FROM chat_messages"
                    " WHERE total_ms IS NOT NULL AND opt_out=0 ORDER BY total_ms"
                ).fetchall()

            # Sorted by the query, so both slices stay sorted for the percentile.
            avg_resp_ms, p95_resp_ms = _latency_summary([r[0] for r in timing_rows])
            avg_resp_ms_llm, p95_resp_ms_llm = _latency_summary(
                [r[0] for r in timing_rows if r[1] not in FIXED_LATENCY_TIERS]
            )

            avg_steps = _mean([r[0] for r in step_rows])
            avg_steps_llm = _mean(
                [r[0] for r in step_rows if r[1] not in FIXED_LATENCY_TIERS]
            )

            avg_msg_per_session = (
                round(total_messages / total_sessions, 1) if total_sessions else None
            )

            return {
                "total_messages": total_messages,
                "total_sessions": total_sessions,
                "avg_messages_per_session": avg_msg_per_session,
                "feedback_good": good,
                "feedback_bad": bad,
                "bad_answers_unreviewed": new_bad,
                "avg_step_count": avg_steps,
                "avg_step_count_llm": avg_steps_llm,
                "avg_resp_ms": avg_resp_ms,
                "p95_resp_ms": p95_resp_ms,
                "avg_resp_ms_llm": avg_resp_ms_llm,
                "p95_resp_ms_llm": p95_resp_ms_llm,
            }
        except Exception:
            logger.exception("Failed to query chat stats")
            return {}

    def get_question_tree_stats(self) -> list[dict]:
        """Per-question click counts, grouped by the tree revision in force.

        Counts are never summed across revisions: the same question_id can be
        reworded between revisions, so pooling them would compare answers to
        different questions. Rows predating version tracking are reported under
        a null version rather than folded into the current one.
        """
        try:
            with self._lock:
                conn = self._connect()
                rows = conn.execute(
                    """
                    SELECT question_tree_version,
                           question_id,
                           parent_question_id,
                           COUNT(*) AS clicks,
                           SUM(CASE WHEN feedback='good' THEN 1 ELSE 0 END),
                           SUM(CASE WHEN feedback='bad' THEN 1 ELSE 0 END),
                           MAX(ts)
                    FROM chat_messages
                    WHERE question_id IS NOT NULL AND opt_out=0
                    GROUP BY question_tree_version, question_id, parent_question_id
                    ORDER BY clicks DESC
                    """
                ).fetchall()
            return [
                {
                    "question_tree_version": r[0],
                    "question_id": r[1],
                    "parent_question_id": r[2],
                    "clicks": r[3],
                    "feedback_good": r[4] or 0,
                    "feedback_bad": r[5] or 0,
                    "last_ts": r[6],
                }
                for r in rows
            ]
        except Exception:
            logger.exception("Failed to query question tree stats")
            return []

    def get_typed_question_counts(self) -> list[dict]:
        """Totals for free-typed questions, split by tree revision.

        Chip clicks only tell half the story — the ratio of typed to canned
        questions is what says whether the suggested tree is covering what
        people actually want to ask.
        """
        try:
            with self._lock:
                conn = self._connect()
                rows = conn.execute(
                    """
                    SELECT question_tree_version, COUNT(*)
                    FROM chat_messages
                    WHERE question_id IS NULL AND opt_out=0
                    GROUP BY question_tree_version
                    """
                ).fetchall()
            return [{"question_tree_version": r[0], "typed": r[1]} for r in rows]
        except Exception:
            logger.exception("Failed to query typed question counts")
            return []

    def get_typed_question_entry_points(self, limit: int = 2000) -> list[dict]:
        """Where in the suggested tree people give up and start typing.

        For each free-typed question, reports the last chip the same session
        clicked before it. A question that repeatedly precedes typing is one
        whose follow-ups do not cover what people wanted next — which is the
        signal for where to add canned questions.

        `after_question_id` is None when the session typed without ever using a
        chip, i.e. the suggestions were bypassed entirely.
        """
        try:
            with self._lock:
                conn = self._connect()
                rows = conn.execute(
                    """
                    SELECT session_id, question_id, question_tree_version, question
                    FROM chat_messages
                    WHERE opt_out=0
                    ORDER BY session_id, ts, rowid
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        except Exception:
            logger.exception("Failed to query typed question entry points")
            return []

        # SQLite has no "last non-null value over a window", so the running
        # last-chip-per-session is tracked here instead.
        buckets: dict[tuple[str | None, str | None], dict] = {}
        last_chip: dict[str, str | None] = {}
        for session_id, question_id, version, question in rows:
            if question_id is not None:
                last_chip[session_id] = question_id
                continue
            key = (version, last_chip.get(session_id))
            bucket = buckets.setdefault(
                key,
                {
                    "question_tree_version": version,
                    "after_question_id": last_chip.get(session_id),
                    "typed": 0,
                    "examples": [],
                },
            )
            bucket["typed"] += 1
            if question and len(bucket["examples"]) < 3:
                bucket["examples"].append(question)

        return sorted(buckets.values(), key=lambda b: -b["typed"])


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
