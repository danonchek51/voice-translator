"""Лёгкая статистика по истории.

Считается по запросу при открытии вкладки, не в реальном времени.
Если история выключена — доступна только сессионная статистика в памяти.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from voiceflow.core.history.repository import HistoryEntry, HistoryRepository


@dataclass(slots=True)
class HistoryStats:
    fragments: int = 0
    total_duration_ms: int = 0
    total_words: int = 0
    total_chars: int = 0
    average_elapsed_ms: float = 0.0


@dataclass(slots=True)
class SessionStats:
    """Статистика текущей сессии, когда база выключена."""

    fragments: int = 0
    total_duration_ms: int = 0
    total_words: int = 0
    total_chars: int = 0
    total_elapsed_ms: int = 0
    entries: list[HistoryEntry] = field(default_factory=list)

    def add(self, entry: HistoryEntry) -> None:
        self.fragments += 1
        self.total_duration_ms += entry.duration_ms
        words = len(entry.final_text.split())
        self.total_words += words
        self.total_chars += len(entry.final_text)
        self.total_elapsed_ms += entry.elapsed_ms
        self.entries.append(entry)

    def as_stats(self) -> HistoryStats:
        avg = self.total_elapsed_ms / self.fragments if self.fragments else 0.0
        return HistoryStats(
            fragments=self.fragments,
            total_duration_ms=self.total_duration_ms,
            total_words=self.total_words,
            total_chars=self.total_chars,
            average_elapsed_ms=avg,
        )


def compute_stats(repository: HistoryRepository) -> HistoryStats:
    entries = repository.list_entries()
    if not entries:
        return HistoryStats()
    duration = sum(e.duration_ms for e in entries)
    words = sum(len(e.final_text.split()) for e in entries)
    chars = sum(len(e.final_text) for e in entries)
    elapsed = sum(e.elapsed_ms for e in entries)
    return HistoryStats(
        fragments=len(entries),
        total_duration_ms=duration,
        total_words=words,
        total_chars=chars,
        average_elapsed_ms=elapsed / len(entries),
    )
