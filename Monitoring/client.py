from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
from pathlib import Path
import sqlite3
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class MonitoringConfig:
    """Monitoring storage configuration."""

    db_path: str = "Monitoring/monitoring.db"


class MonitoringClient:
    """SQLite-backed monitoring for events, metrics, and alerts."""

    def __init__(self, config: Optional[MonitoringConfig] = None) -> None:
        self._config = config or MonitoringConfig()
        self._ensure_schema()

    def _is_quiet_event(self, message: str) -> bool:
        config_path = Path(__file__).resolve().parents[1] / "config" / "app.json"
        if not config_path.exists():
            return False
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            return False
        quiet = data.get("quiet_events")
        if not isinstance(quiet, list):
            return False
        for rule in quiet:
            if not isinstance(rule, str):
                continue
            rule = rule.strip()
            if not rule:
                continue
            if rule.endswith("*") and message.startswith(rule[:-1]):
                return True
            if rule == message:
                return True
        return False

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._config.db_path)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    value REAL NOT NULL,
                    tags TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    severity TEXT NOT NULL,
                    title TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS stats (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            conn.commit()

    def log_event(self, message: str, level: str = "INFO") -> None:
        if not message.strip():
            return
        payload = message.strip()
        if self._is_quiet_event(payload):
            return
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO events (level, message, created_at)
                VALUES (?, ?, ?)
                """,
                (level.upper(), payload, datetime.utcnow().isoformat()),
            )
            conn.commit()
        logger.info("%s: %s", level.upper(), payload)

    def log_metric(self, name: str, value: float, tags: str | None = None) -> None:
        if not name.strip():
            return
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO metrics (name, value, tags, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (name.strip(), float(value), tags, datetime.utcnow().isoformat()),
            )
            conn.commit()

    def raise_alert(self, title: str, detail: str, severity: str = "WARN") -> None:
        if not title.strip() or not detail.strip():
            return
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO alerts (severity, title, detail, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (severity.upper(), title.strip(), detail.strip(), datetime.utcnow().isoformat()),
            )
            conn.commit()
        logger.warning("ALERT %s: %s - %s", severity.upper(), title.strip(), detail.strip())

    def get_recent_events(self, limit: int = 50) -> List[str]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT level, message, created_at FROM events
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [f"{level} {created_at} {message}" for level, message, created_at in rows]

    def get_recent_alerts(self, limit: int = 20) -> List[str]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT severity, title, detail, created_at FROM alerts
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [f"{severity} {created_at} {title}: {detail}" for severity, title, detail, created_at in rows]

    def set_stat(self, key: str, value: str) -> None:
        if not key:
            return
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO stats (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value, datetime.utcnow().isoformat()),
            )
            conn.commit()

    def increment_stat(self, key: str, delta: int = 1) -> None:
        if not key:
            return
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM stats WHERE key = ?", (key,)).fetchone()
            current = int(row[0]) if row and row[0].isdigit() else 0
            value = str(current + delta)
            conn.execute(
                """
                INSERT INTO stats (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value, datetime.utcnow().isoformat()),
            )
            conn.commit()

    def get_stats(self) -> dict:
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value, updated_at FROM stats").fetchall()
        return {key: {"value": value, "updated_at": updated_at} for key, value, updated_at in rows}
