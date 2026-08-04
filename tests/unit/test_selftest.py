"""Четыре проверки диагностики на подставных подсистемах."""

from __future__ import annotations

from tests.fakes import FakeClipboard, FakePaster, FakeRegistry, FakeWindows
from voiceflow.core.asr.base import TranscriberError
from voiceflow.core.audio.level import LevelReading
from voiceflow.core.delivery import ResultDelivery
from voiceflow.core.diagnostics.selftest import (
    SAMPLE_TEXT,
    check_microphone,
    check_paste,
    check_processing,
    check_recognition,
)
from voiceflow.core.settings.schema import OutputSettings, ProcessingSettings
from voiceflow.core.text.processor import TextProcessor


class CaptureStub:
    """Поток захвата с заранее заданным уровнем."""

    def __init__(self, running: bool = True, peak: float = 0.4) -> None:
        self.is_running = running
        self._peak = peak

    @property
    def level(self) -> LevelReading:
        return LevelReading(rms=self._peak / 2, peak=self._peak)


def _no_sleep(_seconds: float) -> None:
    return None


# --------------------------------------------------------------------------- #
# Микрофон
# --------------------------------------------------------------------------- #


def test_microphone_reports_signal() -> None:
    result = check_microphone(CaptureStub(peak=0.4), steps=3, sleep=_no_sleep)

    assert result.ok
    assert "0.40" in result.detail


def test_microphone_without_signal_gives_hint() -> None:
    result = check_microphone(CaptureStub(peak=0.0), steps=3, sleep=_no_sleep)

    assert not result.ok
    assert result.hint


def test_microphone_closed_stream_points_at_pause() -> None:
    result = check_microphone(CaptureStub(running=False), steps=1, sleep=_no_sleep)

    assert not result.ok
    assert "прослушивания" in result.hint


# --------------------------------------------------------------------------- #
# Распознавание
# --------------------------------------------------------------------------- #


def test_recognition_describes_ready_engine() -> None:
    result = check_recognition(FakeRegistry())

    assert result.ok
    assert "fake-model" in result.detail


def test_recognition_without_model_points_at_models_tab() -> None:
    registry = FakeRegistry()
    registry.error = TranscriberError("Ни один движок не готов")

    result = check_recognition(registry)

    assert not result.ok
    assert "Модели" in result.hint


# --------------------------------------------------------------------------- #
# Обработка
# --------------------------------------------------------------------------- #


def _processor(use_llm: bool = False, **steps: bool) -> TextProcessor:
    settings = ProcessingSettings(use_llm=use_llm, clean_enabled=True)
    for key, value in steps.items():
        setattr(settings, key, value)
    return TextProcessor(
        settings_provider=lambda: settings,
        fillers_provider=lambda: ("ну", "вот", "значит", "это самое"),
    )


def test_processing_cleans_sample_without_microphone() -> None:
    result = check_processing(_processor())

    assert result.ok
    # Неприкасаемый фрагмент обязан пережить очистку.
    assert "src/voiceflow/app.py" in result.detail
    assert "значит" not in result.detail


def test_processing_reports_degradation_without_llm() -> None:
    result = check_processing(_processor(use_llm=True, translate_enabled=True))

    assert result.ok
    assert "Без языковой модели" in result.detail


def test_processing_reports_applied_chain() -> None:
    result = check_processing(_processor())

    assert "Применено:" in result.detail


def test_processing_survives_broken_processor() -> None:
    class Boom:
        def process(self, raw: str) -> None:
            raise RuntimeError("нет обработчика")

    result = check_processing(Boom())

    assert not result.ok
    assert "нет обработчика" in result.detail


def test_sample_text_contains_untouchable_fragment() -> None:
    assert "src/voiceflow/app.py" in SAMPLE_TEXT


# --------------------------------------------------------------------------- #
# Вставка
# --------------------------------------------------------------------------- #


def _delivery(**kwargs: object) -> tuple[ResultDelivery, FakePaster]:
    paster = FakePaster()
    settings = OutputSettings(**kwargs)  # type: ignore[arg-type]
    delivery = ResultDelivery(
        settings_provider=lambda: settings,
        clipboard=FakeClipboard(),
        windows=FakeWindows(),
        paster=paster,
        sleep=_no_sleep,
    )
    return delivery, paster


def test_paste_reports_success() -> None:
    delivery, paster = _delivery(paste_delay_ms=0)

    result = check_paste(delivery)

    assert result.ok
    assert paster.paste_calls == ["ctrl_v"]
    assert not result.hint


def test_paste_falls_back_to_clipboard_with_hint() -> None:
    delivery, paster = _delivery(paste_delay_ms=0)
    paster.succeed = False

    result = check_paste(delivery)

    # Текст сохранён в буфере, поэтому проверка не считается провалом.
    assert result.ok
    assert "Ctrl+V" in result.hint
