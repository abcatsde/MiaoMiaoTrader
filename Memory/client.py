from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
import sqlite3
from typing import Iterable, List, Optional, Sequence

logger = logging.getLogger(__name__)


@dataclass
class MemoryConfig:
    """Memory storage configuration."""

    db_path: str = "Memory/memory.db"
    summary_retention_days: int = 90
    error_retention_days: int = 180
    focus_decay_days: int = 14
    focus_min_weight: int = 1


class MemoryClient:
    """SQLite-backed long-term memory storage."""

    def __init__(self, config: Optional[MemoryConfig] = None) -> None:
        self._config = config or MemoryConfig()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._config.db_path)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS focus_pairs (
                    pair TEXT PRIMARY KEY,
                    weight INTEGER NOT NULL DEFAULT 1,
                    last_seen TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS error_learnings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    error TEXT NOT NULL,
                    lesson TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.commit()

    def upsert_focus_pairs(self, pairs: Sequence[str]) -> None:
        now = datetime.utcnow().isoformat()
        pairs = [p.strip().upper() for p in pairs if p and p.strip()]
        if not pairs:
            return
        with self._connect() as conn:
            for pair in pairs:
                conn.execute(
                    """
                    INSERT INTO focus_pairs (pair, weight, last_seen)
                    VALUES (?, 1, ?)
                    ON CONFLICT(pair) DO UPDATE SET
                        weight = weight + 1,
                        last_seen = excluded.last_seen
                    """,
                    (pair, now),
                )
            conn.commit()

    def get_focus_pairs(self, limit: int = 5) -> List[str]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT pair FROM focus_pairs
                ORDER BY weight DESC, last_seen DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [row[0] for row in rows]

    def decay_focus_pairs(self) -> None:
        """Decay focus weights for stale pairs."""
        cutoff = datetime.utcnow().timestamp() - self._config.focus_decay_days * 86400
        cutoff_iso = datetime.utcfromtimestamp(cutoff).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE focus_pairs
                SET weight = MAX(weight - 1, 0)
                WHERE last_seen < ?
                """,
                (cutoff_iso,),
            )
            conn.commit()

    def prune_focus_pairs(self, min_weight: Optional[int] = None) -> None:
        threshold = min_weight if min_weight is not None else self._config.focus_min_weight
        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM focus_pairs
                WHERE weight <= ?
                """,
                (threshold - 1,),
            )
            conn.commit()

    def add_summary(self, kind: str, content: str) -> None:
        if not content.strip():
            return
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO summaries (kind, content, created_at)
                VALUES (?, ?, ?)
                """,
                (kind, content.strip(), datetime.utcnow().isoformat()),
            )
            conn.commit()

    def get_recent_summaries(self, kind: str, limit: int = 5) -> List[str]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT content FROM summaries
                WHERE kind = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (kind, limit),
            ).fetchall()
        return [row[0] for row in rows]

    def add_error_learning(self, error: str, lesson: str) -> None:
        if not error.strip() or not lesson.strip():
            return
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO error_learnings (error, lesson, created_at)
                VALUES (?, ?, ?)
                """,
                (error.strip(), lesson.strip(), datetime.utcnow().isoformat()),
            )
            conn.commit()

    def get_recent_error_learnings(self, limit: int = 3) -> List[str]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT error, lesson FROM error_learnings
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [f"{error} -> {lesson}" for error, lesson in rows]

    def apply_retention(self) -> None:
        """Prune old summaries and error learnings based on retention policy."""
        summary_cutoff = datetime.utcnow().timestamp() - self._config.summary_retention_days * 86400
        error_cutoff = datetime.utcnow().timestamp() - self._config.error_retention_days * 86400
        summary_cutoff_iso = datetime.utcfromtimestamp(summary_cutoff).isoformat()
        error_cutoff_iso = datetime.utcfromtimestamp(error_cutoff).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM summaries
                WHERE created_at < ?
                """,
                (summary_cutoff_iso,),
            )
            conn.execute(
                """
                DELETE FROM error_learnings
                WHERE created_at < ?
                """,
                (error_cutoff_iso,),
            )
            conn.commit()
