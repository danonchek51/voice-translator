"""Страж коммита: что именно он не пускает в репозиторий."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

# Скрипт лежит вне пакета, поэтому загружаем его по пути, а не импортом.
_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_commit_files.py"
_spec = importlib.util.spec_from_file_location("check_commit_files", _SCRIPT)
assert _spec is not None and _spec.loader is not None
_guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_guard)

check = _guard.check
MAX_BYTES = _guard.MAX_BYTES


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Пути приходят от git относительными, поэтому меняем текущую папку."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _make(relative: str, size: int = 16) -> str:
    """Создаёт файл и отдаёт путь так же, как его передаёт pre-commit."""
    path = Path(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return relative


def test_source_files_pass(workdir: Path) -> None:
    files = [
        _make("src/voiceflow/app.py"),
        _make("config/models.toml"),
        _make("README.md"),
    ]

    assert check(files) == []


def test_model_files_are_blocked(workdir: Path) -> None:
    files = [_make("models/asr/model.onnx"), _make("llm/qwen.gguf")]

    problems = check(files)

    assert len(problems) == 2
    assert all("модели и аудио" in problem for problem in problems)


def test_audio_fixtures_are_allowed(workdir: Path) -> None:
    allowed = _make("tests/fixtures/audio/фраза.wav")
    forbidden = _make("docs/запись.wav")

    problems = check([allowed, forbidden])

    assert len(problems) == 1
    assert "docs" in problems[0]


def test_windows_separators_are_understood(workdir: Path) -> None:
    """Git отдаёт пути через прямой слэш, но хук могут вызвать и иначе."""
    _make("tests/fixtures/audio/фраза.wav")

    assert check([r"tests\fixtures\audio\фраза.wav"]) == []


def test_large_file_is_blocked(workdir: Path) -> None:
    big = _make("docs/большой.pdf", size=MAX_BYTES + 1)

    problems = check([big])

    assert len(problems) == 1
    assert "больше предела" in problems[0]


def test_user_data_is_blocked(workdir: Path) -> None:
    files = [
        _make("settings.toml"),
        _make("glossary.toml"),
        _make("data/history.db"),
        _make(".env"),
    ]

    problems = check(files)

    assert len(problems) == 4
    assert all("пользовательские данные" in problem for problem in problems)


def test_missing_paths_are_ignored(workdir: Path) -> None:
    """Git может передать удалённый файл — падать на этом нельзя."""
    assert check(["нет-такого.py"]) == []
