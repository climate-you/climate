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
            conn.commit()
            self._conn = conn
        return self._conn

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
