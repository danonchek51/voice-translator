"""История на SQLite: лимит, тримминг, очистка."""

from __future__ import annotations

from pathlib import Path

from voiceflow.core.history.repository import HistoryRepository
from voiceflow.core.history.stats import compute_stats
from voiceflow.core.settings.schema import HistorySettings


def test_disabled_history_does_not_create_db(tmp_path: Path) -> None:
    db = tmp_path / "history.db"
    repo = HistoryRepository(
        settings_provider=lambda: HistorySettings(enabled=False, max_entries=50),
        db_path=db,
    )
    assert repo.add(raw_text="a", clean_text="a", final_text="a", mode="raw") is None
    assert not db.exists()


def test_zero_limit_skips_db(tmp_path: Path) -> None:
    db = tmp_path / "history.db"
    repo = HistoryRepository(
        settings_provider=lambda: HistorySettings(enabled=True, max_entries=0),
        db_path=db,
    )
    assert repo.add(raw_text="a", clean_text="a", final_text="a", mode="raw") is None
    assert not db.exists()


def test_trim_keeps_newest(tmp_path: Path) -> None:
    db = tmp_path / "history.db"
    settings = HistorySettings(enabled=True, max_entries=50)
    repo = HistoryRepository(settings_provider=lambda: settings, db_path=db)

    for i in range(200):
        repo.add(
            raw_text=f"raw-{i}",
            clean_text=f"clean-{i}",
            final_text=f"final-{i}",
            mode="clean",
            duration_ms=100,
            elapsed_ms=50,
        )

    entries = repo.list_entries()
    assert len(entries) == 50
    assert entries[0].final_text == "final-199"
    assert entries[-1].final_text == "final-150"
    assert repo.count() == 50


def test_delete_and_clear(tmp_path: Path) -> None:
    db = tmp_path / "history.db"
    repo = HistoryRepository(
        settings_provider=lambda: HistorySettings(enabled=True, max_entries=10),
        db_path=db,
    )
    first = repo.add(raw_text="a", clean_text="a", final_text="a", mode="raw")
    second = repo.add(raw_text="b", clean_text="b", final_text="b", mode="raw")
    assert first is not None and second is not None
    assert repo.delete(first.id)
    assert repo.count() == 1
    repo.clear()
    assert repo.count() == 0


def test_stats(tmp_path: Path) -> None:
    db = tmp_path / "history.db"
    repo = HistoryRepository(
        settings_provider=lambda: HistorySettings(enabled=True, max_entries=10),
        db_path=db,
    )
    repo.add(
        raw_text="один два",
        clean_text="один два",
        final_text="один два",
        mode="clean",
        duration_ms=1000,
        elapsed_ms=200,
    )
    stats = compute_stats(repo)
    assert stats.fragments == 1
    assert stats.total_words == 2
    assert stats.average_elapsed_ms == 200
