"""Per-stage timing to SQLite (PERF-01, D-16).

Shares jarvis.db with the audit log. Each turn writes one row per pipeline
stage (wake, gate, ack, record, stt, brain, tts_first_audio, tts_done) with
elapsed_ms from turn start. Queryable for latency regression detection.

Pattern follows :class:`AuditLog` in ``core/audit.py``.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class TimingLog:
    """Write per-stage timing rows to the ``timing`` table in jarvis.db."""

    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS timing (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                turn_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                elapsed_ms INTEGER NOT NULL
            )
        """)
        self.conn.commit()

    def insert(self, turn_id: str, stage: str, elapsed_ms: int) -> None:
        """Insert a timing row for one pipeline stage."""
        self.conn.execute(
            "INSERT INTO timing (ts, turn_id, stage, elapsed_ms) VALUES (?, ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), turn_id, stage, elapsed_ms),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
