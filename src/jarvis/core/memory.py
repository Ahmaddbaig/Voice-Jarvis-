"""Persistent memory store for Jarvis (Phase 4 — MEMORY-01..09).

SQLite + sqlite-vec backed storage for conversation turns and extracted facts.
Follows the audit.py WAL+connection pattern. Embeddings generated locally via
sentence-transformers/all-MiniLM-L6-v2 (384-dim) and stored in vec0 virtual
tables for cosine-similarity KNN retrieval.

PII (credit cards, SSNs, US phone numbers) is redacted before embedding but
raw text is preserved in the turns/facts tables. Emails are NOT redacted (D-10).
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import sqlite_vec

# ---------------------------------------------------------------------------
# PII redaction (MEMORY-09 / D-09)
# ---------------------------------------------------------------------------

_PII_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Credit card: 4 groups of 4 digits, optionally separated by - or space
    (re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"), "[REDACTED_CC]"),
    # SSN: NNN-NN-NNNN
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
    # US phone: optional +1, area code (with optional parens), 7 digits
    (
        re.compile(
            r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"
        ),
        "[REDACTED_PHONE]",
    ),
]


def redact_pii(text: str) -> str:
    """Redact PII before embedding. Raw text is preserved elsewhere."""
    for pattern, replacement in _PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


# ---------------------------------------------------------------------------
# MemoryStore
# ---------------------------------------------------------------------------

# Fact types that expire after 90 days
_EXPIRING_TYPES = frozenset({"state", "event"})
_EXPIRY_DAYS = 90


class MemoryStore:
    """Persistent memory backed by SQLite + sqlite-vec.

    Owns the DB connection, schema init, embedding, fact CRUD with typed
    expiry and supersession, turn storage, and semantic retrieval.
    """

    def __init__(self, db_path: Path, embedder: Any) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        # Load sqlite-vec extension
        self.conn.enable_load_extension(True)
        sqlite_vec.load(self.conn)
        self.conn.enable_load_extension(False)
        self.embedder = embedder
        self._init_schema()
        self._expire_stale()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                session_id TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                type TEXT NOT NULL CHECK(type IN ('identity','preference','profile','state','event')),
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'auto',
                expired INTEGER DEFAULT 0,
                superseded_by INTEGER,
                expires_at TEXT
            );
        """)
        self.conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_turns
            USING vec0(embedding float[384] distance_metric=cosine)
        """)
        self.conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_facts
            USING vec0(embedding float[384] distance_metric=cosine)
        """)
        self.conn.commit()

    # ------------------------------------------------------------------
    # Embedding
    # ------------------------------------------------------------------

    def embed(self, text: str) -> np.ndarray:
        """Generate 384-dim float32 embedding. PII is redacted first."""
        clean = redact_pii(text)
        return self.embedder.encode(clean, convert_to_numpy=True).astype(
            np.float32
        )

    # ------------------------------------------------------------------
    # Token budget helper
    # ------------------------------------------------------------------

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Word-count approximation: words * 1.3."""
        return int(len(text.split()) * 1.3)

    # ------------------------------------------------------------------
    # Turn storage (MEMORY-01)
    # ------------------------------------------------------------------

    def store_turn(
        self, role: str, content: str, session_id: str
    ) -> int:
        """Insert a conversation turn and its embedding. Return the turn id."""
        ts = datetime.now(timezone.utc).isoformat()
        cur = self.conn.execute(
            "INSERT INTO turns (ts, role, content, session_id) VALUES (?, ?, ?, ?)",
            (ts, role, content, session_id),
        )
        turn_id = cur.lastrowid
        vec = self.embed(content)
        self.conn.execute(
            "INSERT INTO vec_turns (rowid, embedding) VALUES (?, ?)",
            [turn_id, vec],
        )
        self.conn.commit()
        return turn_id

    # ------------------------------------------------------------------
    # Fact upsert with supersession (MEMORY-06, MEMORY-07)
    # ------------------------------------------------------------------

    def upsert_fact(
        self,
        type: str,
        key: str,
        value: str,
        source: str = "auto",
        supersedes_key: str | None = None,
    ) -> int:
        """Insert a fact, handling automatic supersession and typed expiry."""
        ts = datetime.now(timezone.utc).isoformat()

        # Compute expiry for state/event types
        expires_at: str | None = None
        if type in _EXPIRING_TYPES:
            expires_at = (
                datetime.now(timezone.utc) + timedelta(days=_EXPIRY_DAYS)
            ).isoformat()

        # Insert the new fact first to get its id
        cur = self.conn.execute(
            "INSERT INTO facts (ts, type, key, value, source, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ts, type, key, value, source, expires_at),
        )
        new_id = cur.lastrowid

        # Supersede by explicit key if provided
        if supersedes_key is not None:
            self.conn.execute(
                "UPDATE facts SET superseded_by = ? "
                "WHERE type = ? AND key = ? AND superseded_by IS NULL "
                "AND expired = 0 AND id != ?",
                (new_id, type, supersedes_key, new_id),
            )

        # Automatic supersession: same type+key with different value (MEMORY-07)
        self.conn.execute(
            "UPDATE facts SET superseded_by = ? "
            "WHERE type = ? AND key = ? AND superseded_by IS NULL "
            "AND expired = 0 AND id != ? AND value != ?",
            (new_id, type, key, new_id, value),
        )

        # Insert embedding into vec_facts
        vec = self.embed(f"{key}: {value}")
        self.conn.execute(
            "INSERT INTO vec_facts (rowid, embedding) VALUES (?, ?)",
            [new_id, vec],
        )
        self.conn.commit()
        return new_id

    # ------------------------------------------------------------------
    # Expire stale facts (MEMORY-06 / D-05)
    # ------------------------------------------------------------------

    def _expire_stale(self) -> int:
        """Soft-delete facts past their expires_at. Returns count expired."""
        cur = self.conn.execute(
            "UPDATE facts SET expired = 1 "
            "WHERE expires_at IS NOT NULL AND expires_at < datetime('now') "
            "AND expired = 0"
        )
        self.conn.commit()
        return cur.rowcount

    # ------------------------------------------------------------------
    # Profile facts query (D-07 Block 1)
    # ------------------------------------------------------------------

    def get_profile_facts(self) -> list[dict]:
        """Return non-expired, non-superseded identity/preference/profile facts."""
        rows = self.conn.execute(
            "SELECT type, key, value, ts FROM facts "
            "WHERE type IN ('identity', 'preference', 'profile') "
            "AND expired = 0 AND superseded_by IS NULL "
            "ORDER BY ts DESC"
        ).fetchall()
        return [
            {"type": r[0], "key": r[1], "value": r[2], "ts": r[3]}
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Semantic recall (MEMORY-02, MEMORY-04, MEMORY-05)
    # ------------------------------------------------------------------

    def recall_similar(
        self, query_text: str, k: int = 5, threshold: float = 0.7
    ) -> list[dict]:
        """Return top-K similar turns and facts, merged and sorted.

        Each result includes a ``confident`` flag (similarity >= threshold).
        Results below threshold are tagged uncertain (MEMORY-05).
        """
        query_vec = self.embed(query_text)
        results: list[dict] = []

        # Similar turns
        turn_rows = self.conn.execute(
            """
            WITH knn AS (
                SELECT rowid, distance FROM vec_turns
                WHERE embedding MATCH ? AND k = ?
            )
            SELECT turns.id, turns.ts, turns.role, turns.content, knn.distance
            FROM knn LEFT JOIN turns ON turns.id = knn.rowid
            ORDER BY knn.distance ASC
            """,
            [query_vec, k],
        ).fetchall()
        for r in turn_rows:
            sim = 1.0 - r[4]
            results.append(
                {
                    "id": r[0],
                    "ts": r[1],
                    "source_type": "turn",
                    "role": r[2],
                    "content": r[3],
                    "similarity": sim,
                    "confident": sim >= threshold,
                }
            )

        # Similar facts (non-expired, non-superseded only)
        fact_rows = self.conn.execute(
            """
            WITH knn AS (
                SELECT rowid, distance FROM vec_facts
                WHERE embedding MATCH ? AND k = ?
            )
            SELECT facts.id, facts.ts, facts.type, facts.key, facts.value,
                   knn.distance
            FROM knn LEFT JOIN facts ON facts.id = knn.rowid
            WHERE facts.expired = 0 AND facts.superseded_by IS NULL
            ORDER BY knn.distance ASC
            """,
            [query_vec, k],
        ).fetchall()
        for r in fact_rows:
            sim = 1.0 - r[5]
            results.append(
                {
                    "id": r[0],
                    "ts": r[1],
                    "source_type": "fact",
                    "type": r[2],
                    "key": r[3],
                    "value": r[4],
                    "similarity": sim,
                    "confident": sim >= threshold,
                }
            )

        # Merge: sort by similarity descending, take top k
        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:k]

    # ------------------------------------------------------------------
    # Recent turns (D-13)
    # ------------------------------------------------------------------

    def get_recent_turns(
        self, n: int = 8, session_id: str | None = None
    ) -> list[dict]:
        """Return last N turns as message dicts for Brain.ask().

        Returns in chronological order (oldest first).
        """
        if session_id:
            rows = self.conn.execute(
                "SELECT role, content FROM turns "
                "WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (session_id, n),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT role, content FROM turns ORDER BY id DESC LIMIT ?",
                (n,),
            ).fetchall()
        # Reverse to chronological order
        return [{"role": r[0], "content": r[1]} for r in reversed(rows)]

    # ------------------------------------------------------------------
    # Fact search for tools
    # ------------------------------------------------------------------

    def search_facts(self, query: str, k: int = 5) -> list[str]:
        """Search facts semantically. Returns formatted strings for tool output."""
        query_vec = self.embed(query)
        rows = self.conn.execute(
            """
            WITH knn AS (
                SELECT rowid, distance FROM vec_facts
                WHERE embedding MATCH ? AND k = ?
            )
            SELECT facts.type, facts.key, facts.value, facts.ts, knn.distance
            FROM knn LEFT JOIN facts ON facts.id = knn.rowid
            WHERE facts.expired = 0 AND facts.superseded_by IS NULL
            ORDER BY knn.distance ASC
            """,
            [query_vec, k],
        ).fetchall()
        results = []
        for r in rows:
            sim = 1.0 - r[4]
            confidence = "uncertain" if sim < 0.7 else ""
            tag = f" ({confidence})" if confidence else ""
            results.append(
                f"[{r[0]}] {r[1]}: {r[2]} (recorded {r[3][:10]}){tag}"
            )
        return results

    # ------------------------------------------------------------------
    # Forget (manual supersession)
    # ------------------------------------------------------------------

    def forget_fact(self, fact_query: str) -> int:
        """Find facts matching query (semantic, top 3), mark as forgotten.

        Uses superseded_by=-1 as the manual-forget sentinel.
        Returns count of forgotten facts.
        """
        query_vec = self.embed(fact_query)
        rows = self.conn.execute(
            """
            WITH knn AS (
                SELECT rowid, distance FROM vec_facts
                WHERE embedding MATCH ? AND k = ?
            )
            SELECT facts.id FROM knn
            LEFT JOIN facts ON facts.id = knn.rowid
            WHERE facts.expired = 0 AND facts.superseded_by IS NULL
            ORDER BY knn.distance ASC
            """,
            [query_vec, 3],
        ).fetchall()
        if not rows:
            return 0
        ids = [r[0] for r in rows]
        placeholders = ",".join("?" * len(ids))
        cur = self.conn.execute(
            f"UPDATE facts SET superseded_by = -1 WHERE id IN ({placeholders})",
            ids,
        )
        self.conn.commit()
        return cur.rowcount

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the database connection."""
        self.conn.close()
