"""Хранилище результатов обработки.

История — собственная, не перехват системного буфера обмена.
При ``max_entries = 0`` база не создаётся вообще.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from voiceflow import paths
from voiceflow.core.history.db import connect
from voiceflow.core.settings.schema import HistorySettings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    id: int
    created_at: str
    duration_ms: int
    mode: str
    language: str
    engine_asr: str
    engine_llm: str
    raw_text: str
    clean_text: str
    final_text: str
    elapsed_ms: int


class HistoryRepository:
    """Потокобезопасный доступ к истории."""

    def __init__(
        self,
        settings_provider: Callable[[], HistorySettings],
        db_path: Path | None = None,
    ) -> None:
        self._settings_provider = settings_provider
        self._db_path = db_path or paths.history_db()
        self._lock = threading.RLock()
        self._connection: sqlite3.Connection | None = None

    def _should_persist(self) -> bool:
        settings = self._settings_provider()
        return settings.enabled and settings.max_entries > 0

    def _ensure(self) -> sqlite3.Connection | None:
        if self._connection is not None:
            return self._connection
        if not self._should_persist():
            return None
        self._connection = connect(self._db_path)
        return self._connection

    def add(
        self,
        *,
        raw_text: str,
        clean_text: str,
        final_text: str,
        mode: str,
        language: str = "",
        engine_asr: str = "",
        engine_llm: str = "",
        duration_ms: int = 0,
        elapsed_ms: int = 0,
    ) -> HistoryEntry | None:
        """Добавляет запись и триммит хвост. ``None`` — история выключена."""
        with self._lock:
            if not self._should_persist():
                return None
            connection = self._ensure()
            if connection is None:
                return None

            created = datetime.now(UTC).replace(microsecond=0).isoformat()
            cursor = connection.execute(
                """
                INSERT INTO history (
                    created_at, duration_ms, mode, language, engine_asr, engine_llm,
                    raw_text, clean_text, final_text, elapsed_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created,
                    duration_ms,
                    mode,
                    language,
                    engine_asr,
                    engine_llm,
                    raw_text,
                    clean_text,
                    final_text,
                    elapsed_ms,
                ),
            )
            entry_id = int(cursor.lastrowid or 0)
            self._trim(connection)
            connection.commit()
            return HistoryEntry(
                id=entry_id,
                created_at=created,
                duration_ms=duration_ms,
                mode=mode,
                language=language,
                engine_asr=engine_asr,
                engine_llm=engine_llm,
                raw_text=raw_text,
                clean_text=clean_text,
                final_text=final_text,
                elapsed_ms=elapsed_ms,
            )

    def _trim(self, connection: sqlite3.Connection) -> None:
        limit = self._settings_provider().max_entries
        if limit <= 0:
            return
        connection.execute(
            """
            DELETE FROM history
            WHERE id NOT IN (
                SELECT id FROM history ORDER BY id DESC LIMIT ?
            )
            """,
            (limit,),
        )

    def list_entries(self, limit: int | None = None) -> list[HistoryEntry]:
        with self._lock:
            connection = self._ensure()
            if connection is None:
                return []
            cap = limit if limit is not None else self._settings_provider().max_entries
            if cap <= 0:
                cap = 100
            rows = connection.execute(
                "SELECT * FROM history ORDER BY id DESC LIMIT ?",
                (cap,),
            ).fetchall()
            return [self._row_to_entry(row) for row in rows]

    def get(self, entry_id: int) -> HistoryEntry | None:
        with self._lock:
            connection = self._ensure()
            if connection is None:
                return None
            row = connection.execute(
                "SELECT * FROM history WHERE id = ?",
                (entry_id,),
            ).fetchone()
            return self._row_to_entry(row) if row else None

    def delete(self, entry_id: int) -> bool:
        with self._lock:
            connection = self._ensure()
            if connection is None:
                return False
            cursor = connection.execute("DELETE FROM history WHERE id = ?", (entry_id,))
            connection.commit()
            return bool(cursor.rowcount > 0)

    def clear(self) -> None:
        with self._lock:
            connection = self._ensure()
            if connection is None:
                return
            connection.execute("DELETE FROM history")
            connection.commit()

    def count(self) -> int:
        with self._lock:
            connection = self._ensure()
            if connection is None:
                return 0
            row = connection.execute("SELECT COUNT(*) AS n FROM history").fetchone()
            return int(row["n"]) if row else 0

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> HistoryEntry:
        return HistoryEntry(
            id=int(row["id"]),
            created_at=str(row["created_at"]),
            duration_ms=int(row["duration_ms"]),
            mode=str(row["mode"]),
            language=str(row["language"]),
            engine_asr=str(row["engine_asr"]),
            engine_llm=str(row["engine_llm"]),
            raw_text=str(row["raw_text"]),
            clean_text=str(row["clean_text"]),
            final_text=str(row["final_text"]),
            elapsed_ms=int(row["elapsed_ms"]),
        )

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None
