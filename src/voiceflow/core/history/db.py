"""Подключение к SQLite истории результатов."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    mode TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL DEFAULT '',
    engine_asr TEXT NOT NULL DEFAULT '',
    engine_llm TEXT NOT NULL DEFAULT '',
    raw_text TEXT NOT NULL DEFAULT '',
    clean_text TEXT NOT NULL DEFAULT '',
    final_text TEXT NOT NULL DEFAULT '',
    elapsed_ms INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_history_created_at ON history(created_at DESC);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    """Открывает базу в режиме WAL и создаёт схему при необходимости."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(db_path), check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL;")
    connection.execute("PRAGMA synchronous=NORMAL;")
    connection.executescript(SCHEMA)
    return connection
