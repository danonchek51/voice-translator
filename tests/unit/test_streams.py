"""Потоки вывода в сборке без консоли.

Без этой защиты любая библиотека, печатающая прогресс, роняет приложение
с невнятным «NoneType has no attribute write», и пользователь видит это как
сбой загрузки модели.
"""

from __future__ import annotations

import sys

import pytest

from voiceflow.streams import NullStream, ensure_output_streams, stream_or_null


def test_null_stream_accepts_everything() -> None:
    stream = NullStream()

    assert stream.write("текст") == 5
    assert stream.writelines(["a", "b"]) is None
    assert stream.flush() is None
    assert stream.isatty() is False
    assert stream.closed is False


def test_null_stream_admits_it_has_no_descriptor() -> None:
    with pytest.raises(OSError):
        NullStream().fileno()


def test_missing_streams_are_replaced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    replaced = ensure_output_streams()

    assert sorted(replaced) == ["stderr", "stdout"]
    assert isinstance(sys.stdout, NullStream)
    assert isinstance(sys.stderr, NullStream)
    # Именно этот вызов падал в собранном приложении.
    print("проверка записи в подменённый поток")


def test_existing_streams_are_left_alone() -> None:
    before_out, before_err = sys.stdout, sys.stderr

    assert ensure_output_streams() == []
    assert sys.stdout is before_out
    assert sys.stderr is before_err


def test_stream_or_null_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stderr", None)

    assert isinstance(stream_or_null("stderr"), NullStream)
    assert stream_or_null("stdout") is sys.stdout


def test_progress_bars_are_disabled_in_cache_setup(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Полосы прогресса библиотеки пишут в поток, которого может не быть."""
    monkeypatch.setenv("VOICEFLOW_HOME", str(tmp_path))
    monkeypatch.delenv("HF_HUB_DISABLE_PROGRESS_BARS", raising=False)
    from voiceflow.core.modelstore.cache import configure_offline_cache

    configure_offline_cache()

    import os

    assert os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] == "1"
