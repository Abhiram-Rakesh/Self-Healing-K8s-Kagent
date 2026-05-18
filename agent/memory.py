"""
SQLite-backed incident memory for improving diagnosis accuracy.

Stores past incident outcomes so the agent can reference similar
cases when diagnosing new failures. Pure stdlib — no extra deps.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = os.environ.get("MEMORY_DB_PATH", "/tmp/kagent-memory.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_type TEXT NOT NULL,
    diagnosis  TEXT NOT NULL,
    action     TEXT NOT NULL,
    outcome    TEXT NOT NULL,
    confidence REAL NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alert_type ON incidents(alert_type);
"""


class RunbookMemory:
    """Thread-safe SQLite store of past healing incidents."""

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or DEFAULT_DB_PATH
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        try:
            with self._lock, self._connect() as conn:
                conn.executescript(_SCHEMA)
                conn.commit()
            logger.info("RunbookMemory initialized at %s", self.db_path)
        except sqlite3.Error as exc:
            logger.error("Failed to initialize memory DB at %s: %s", self.db_path, exc)

    def store(self, entry: dict[str, Any]) -> None:
        """Insert a single incident row. Errors are logged, not raised."""
        try:
            with self._lock, self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO incidents
                        (alert_type, diagnosis, action, outcome, confidence, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(entry.get("alert_type", "unknown")),
                        str(entry.get("diagnosis", "")),
                        str(entry.get("action", "")),
                        str(entry.get("outcome", "")),
                        float(entry.get("confidence", 0.0)),
                        entry.get("created_at")
                        or datetime.now(timezone.utc).isoformat(),
                    ),
                )
                conn.commit()
        except (sqlite3.Error, ValueError, TypeError) as exc:
            logger.error("memory.store failed: %s", exc)

    def recall(self, alert_type: str, limit: int = 3) -> str:
        """Return a readable summary of the last N matching incidents."""
        try:
            with self._lock, self._connect() as conn:
                cur = conn.execute(
                    """
                    SELECT diagnosis, action, outcome, confidence, created_at
                      FROM incidents
                     WHERE alert_type = ?
                     ORDER BY id DESC
                     LIMIT ?
                    """,
                    (alert_type, int(limit)),
                )
                rows = cur.fetchall()
            if not rows:
                return "No past cases."
            lines = []
            for r in rows:
                lines.append(
                    "- [{ts}] diagnosis={diag!r} action={act} "
                    "outcome={out} confidence={conf:.2f}".format(
                        ts=r["created_at"],
                        diag=r["diagnosis"],
                        act=r["action"],
                        out=r["outcome"],
                        conf=float(r["confidence"]),
                    )
                )
            return "\n".join(lines)
        except sqlite3.Error as exc:
            logger.error("memory.recall failed: %s", exc)
            return "Memory unavailable"
