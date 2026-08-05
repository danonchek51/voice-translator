"""Нагрузка распознавания на процессор.

По умолчанию onnxruntime занимает все логические ядра, и на время
распознавания подвисает вся система — вплоть до рывков указателя мыши.
Работа идёт в фоне, пока человек продолжает печатать, поэтому часть ядер
обязана оставаться свободной.
"""

from __future__ import annotations

import pytest

from voiceflow.core.asr.base import MIN_INFERENCE_THREADS, inference_threads


def test_uses_physical_cores_not_logical(monkeypatch: pytest.MonkeyPatch) -> None:
    """Замер показал: половина логических ядер и быстрее, и легче для системы."""
    monkeypatch.setattr("os.cpu_count", lambda: 12)

    assert inference_threads() == 6


def test_never_drops_below_minimum(monkeypatch: pytest.MonkeyPatch) -> None:
    """На двухъядерной машине распознавание не должно остаться без потоков."""
    monkeypatch.setattr("os.cpu_count", lambda: 2)

    assert inference_threads() == MIN_INFERENCE_THREADS


def test_unknown_core_count_is_handled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("os.cpu_count", lambda: None)

    assert inference_threads() >= MIN_INFERENCE_THREADS


def test_never_takes_every_core(monkeypatch: pytest.MonkeyPatch) -> None:
    """Занятые под завязку ядра дают рывки указателя во время работы."""
    for cores in (4, 8, 12, 16, 32):
        monkeypatch.setattr("os.cpu_count", lambda c=cores: c)
        assert inference_threads() < cores


def test_background_thread_yields_to_interface() -> None:
    """Понижение приоритета не должно падать ни на одной системе."""
    from voiceflow.platform.base import lower_current_thread_priority

    assert lower_current_thread_priority() in (True, False)


def test_model_is_loaded_before_the_first_recording() -> None:
    """Иначе пауза в пять-семь секунд приходится на конец первой записи."""
    from voiceflow.core.asr.registry import TranscriberRegistry
    from voiceflow.core.settings.schema import RecognitionSettings

    loaded: list[str] = []

    class FakeTranscriber:
        def load(self) -> None:
            loaded.append("да")

    registry = TranscriberRegistry(RecognitionSettings)
    registry.resolve = lambda: type("R", (), {"transcriber": FakeTranscriber()})()  # type: ignore[method-assign]

    thread = registry.preload()
    assert thread is not None
    thread.join(timeout=5.0)

    assert loaded == ["да"]


def test_preload_survives_missing_model() -> None:
    """Модели может не быть — это штатный случай, а не сбой запуска."""
    from voiceflow.core.asr.base import TranscriberError
    from voiceflow.core.asr.registry import TranscriberRegistry
    from voiceflow.core.settings.schema import RecognitionSettings

    registry = TranscriberRegistry(RecognitionSettings)

    def boom():  # type: ignore[no-untyped-def]
        raise TranscriberError("модель не загружена")

    registry.resolve = boom  # type: ignore[method-assign]

    thread = registry.preload()
    assert thread is not None
    thread.join(timeout=5.0)

    assert not thread.is_alive()


def test_pipeline_lowers_priority_of_its_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    from voiceflow.core import pipeline as pipeline_module

    calls: list[bool] = []
    monkeypatch.setattr(
        pipeline_module, "lower_current_thread_priority", lambda: calls.append(True) or True
    )

    done = []
    runner = pipeline_module.Pipeline._run_in_background
    fake_self = type("S", (), {"_worker": None, "_fail": lambda *a: None})()
    runner(fake_self, lambda: done.append(True))
    fake_self._worker.join(timeout=2.0)

    assert done == [True]
    assert calls == [True], "фоновый поток обязан уступать интерфейсу"
