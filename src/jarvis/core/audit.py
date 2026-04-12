"""SQLite audit log for tool calls (SAFE-02).

Schema designed for future Phase 4 compatibility -- same jarvis.db file.
Row inserted BEFORE execution (status='running'), updated after.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class AuditLog:
    """Write-ahead audit log for every tool invocation."""

    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS tool_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                turn_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                tier INTEGER NOT NULL,
                arguments TEXT NOT NULL,
                result TEXT,
                duration_ms INTEGER,
                status TEXT NOT NULL DEFAULT 'running'
            )
        """)
        self.conn.commit()

    def insert_pending(self, turn_id: str, tool_name: str, tier: int, arguments: dict) -> int:
        """Insert BEFORE execution with status='running'."""
        cur = self.conn.execute(
            "INSERT INTO tool_calls (ts, turn_id, tool_name, tier, arguments, status) VALUES (?, ?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                turn_id,
                tool_name,
                tier,
                json.dumps(arguments),
                "running",
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    def update_result(self, row_id: int, result: str, duration_ms: int, status: str = "ok") -> None:
        """Update after execution completes."""
        self.conn.execute(
            "UPDATE tool_calls SET result=?, duration_ms=?, status=? WHERE id=?",
            (result[:4000], duration_ms, status, row_id),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
