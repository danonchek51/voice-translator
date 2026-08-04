"""Конвейер целиком на подставных подсистемах.

Проверяются переходы состояний, порядок событий, откат при сбое и отсутствие
зависаний — всё без микрофона, моделей и сети.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import numpy as np
import pytest

from tests.fakes import (
    FakeCapture,
    FakeClipboard,
    FakePaster,
    FakeRegistry,
    FakeTranscriber,
    FakeWindows,
)
from voiceflow.core.asr.base import ModelNotReadyError
from voiceflow.core.delivery import ResultDelivery
from voiceflow.core.events import (
    ErrorOccurred,
    Event,
    EventBus,
    NoticeIssued,
    RecordingFinished,
    RecordingStarted,
    ResultDelivered,
    TextProcessed,
    TranscriptReady,
)
from voiceflow.core.pipeline import Pipeline
from voiceflow.core.settings.schema import Settings
from voiceflow.core.state import AppState, StateMachine
from voiceflow.core.text.glossary import Glossary
from voiceflow.core.text.processor import TextProcessor
from voiceflow.core.triggers import TriggerSource


class Harness:
    """Собранный конвейер и журнал всех событий."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.bus = EventBus()
        self.state = StateMachine()
        self.capture = FakeCapture()
        self.registry = FakeRegistry()
        self.clipboard = FakeClipboard()
        self.windows = FakeWindows()
        self.paster = FakePaster()
        self.events: list[Event] = []
        self.states: list[AppState] = []

        self.bus.subscribe(Event, self.events.append)
        self.state.add_listener(lambda old, new, detail: self.states.append(new))

        self.delivery = ResultDelivery(
            settings_provider=lambda: self.settings.output,
            clipboard=self.clipboard,
            windows=self.windows,
            paster=self.paster,
            sleep=lambda seconds: None,
        )
        self.processor = TextProcessor(
            settings_provider=lambda: self.settings.processing,
            glossary_provider=Glossary,
            fillers_provider=lambda: ("ну", "короче", "как бы"),
        )
        self.pipeline = Pipeline(
            settings_provider=lambda: self.settings,
            bus=self.bus,
            state=self.state,
            capture=self.capture,  # type: ignore[arg-type]
            transcribers=self.registry,  # type: ignore[arg-type]
            delivery=self.delivery,
            processor=self.processor,
        )

    def of_type(self, event_type: type[Event]) -> list[Event]:
        return [event for event in self.events if isinstance(event, event_type)]

    def wait_idle(self, timeout: float = 3.0) -> bool:
        return wait_for(lambda: self.state.state is AppState.IDLE, timeout)

    def wait_for_event(self, event_type: type[Event], timeout: float = 3.0) -> bool:
        return wait_for(lambda: bool(self.of_type(event_type)), timeout)


def wait_for(predicate: Callable[[], bool], timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


@pytest.fixture
def harness() -> Harness:
    return Harness(Settings())


# --------------------------------------------------------------------------- #
# Основной сценарий
# --------------------------------------------------------------------------- #


def test_full_cycle_reaches_idle_with_text(harness: Harness) -> None:
    harness.pipeline.start_recording(TriggerSource.HOTKEY)

    assert harness.state.state is AppState.RECORDING
    assert harness.capture.is_recording is True

    harness.pipeline.stop_recording()

    assert harness.wait_idle()
    assert harness.states == [
        AppState.RECORDING,
        AppState.TRANSCRIBING,
        AppState.PROCESSING,
        AppState.PASTING,
        AppState.IDLE,
    ]

    transcripts = harness.of_type(TranscriptReady)
    assert len(transcripts) == 1
    assert transcripts[0].text == "тестовый текст"  # type: ignore[attr-defined]


def test_text_is_cleaned_before_delivery(harness: Harness) -> None:
    harness.registry.transcriber = FakeTranscriber(text="ну короче надо переделать")

    harness.pipeline.start_recording(TriggerSource.HOTKEY)
    harness.pipeline.stop_recording()
    assert harness.wait_idle()

    processed = harness.of_type(TextProcessed)
    assert processed[0].final == "Надо переделать"  # type: ignore[attr-defined]
    assert harness.clipboard.text == "Надо переделать"


def test_all_steps_off_skips_cleanup(harness: Harness) -> None:
    harness.settings.processing.clean_enabled = False
    harness.registry.transcriber = FakeTranscriber(text="ну короче надо переделать")

    harness.pipeline.start_recording(TriggerSource.HOTKEY)
    harness.pipeline.stop_recording()
    assert harness.wait_idle()

    assert harness.clipboard.text == "ну короче надо переделать"


def test_enabled_steps_reflect_settings(harness: Harness) -> None:
    harness.settings.processing.clean_enabled = True
    harness.settings.processing.translate_enabled = True

    assert harness.pipeline.steps == ("clean", "translate")

    harness.settings.processing.clean_enabled = False
    harness.settings.processing.translate_enabled = False
    harness.settings.processing.prompt_mode_enabled = False

    assert harness.pipeline.steps == ()


def test_steps_are_reported_in_event(harness: Harness) -> None:
    harness.registry.transcriber = FakeTranscriber(text="ну короче текст")

    harness.pipeline.start_recording(TriggerSource.HOTKEY)
    harness.pipeline.stop_recording()
    assert harness.wait_idle()

    processed = harness.of_type(TextProcessed)
    assert processed
    # Языковой модели в стенде нет, поэтому шаги не применились,
    # но очистка правилами всё равно сработала.
    assert processed[0].steps == ()
    assert harness.clipboard.text == "Текст"


def test_technical_terms_survive_the_whole_pipeline(harness: Harness) -> None:
    """Главное продуктовое требование: путь и адрес не должны исказиться."""
    harness.registry.transcriber = FakeTranscriber(
        text="ну короче открой C:\\project\\main.py и глянь https://example.com/api"
    )

    harness.pipeline.start_recording(TriggerSource.HOTKEY)
    harness.pipeline.stop_recording()
    assert harness.wait_idle()

    delivered = harness.clipboard.text or ""
    assert "C:\\project\\main.py" in delivered
    assert "https://example.com/api" in delivered
    assert "короче" not in delivered


def test_result_reaches_clipboard_and_target_window(harness: Harness) -> None:
    harness.pipeline.start_recording(TriggerSource.HOTKEY)
    harness.pipeline.stop_recording()
    assert harness.wait_idle()

    # Текст доходит уже очищенным: с заглавной буквы в начале предложения.
    assert harness.clipboard.text == "Тестовый текст"
    assert harness.paster.paste_calls == ["ctrl_v"]
    delivered = harness.of_type(ResultDelivered)
    assert delivered[0].pasted is True  # type: ignore[attr-defined]


def test_target_window_is_captured_at_recording_start(harness: Harness) -> None:
    """Пользователь может переключиться, пока идёт распознавание."""
    harness.pipeline.start_recording(TriggerSource.HOTKEY)
    harness.windows.target = None

    harness.pipeline.stop_recording()
    assert harness.wait_idle()

    delivered = harness.of_type(ResultDelivered)
    assert delivered[0].target == "notepad.exe — Блокнот"  # type: ignore[attr-defined]


def test_failed_paste_keeps_text_in_clipboard(harness: Harness) -> None:
    harness.paster.succeed = False

    harness.pipeline.start_recording(TriggerSource.HOTKEY)
    harness.pipeline.stop_recording()
    assert harness.wait_idle()

    assert harness.clipboard.text == "Тестовый текст"
    delivered = harness.of_type(ResultDelivered)
    assert delivered[0].copied is True  # type: ignore[attr-defined]
    assert delivered[0].pasted is False  # type: ignore[attr-defined]


def test_clipboard_failure_raises_error_state(harness: Harness) -> None:
    harness.clipboard.fail_on_set = True

    harness.pipeline.start_recording(TriggerSource.HOTKEY)
    harness.pipeline.stop_recording()

    assert wait_for(lambda: harness.state.state is AppState.ERROR)
    assert harness.of_type(ErrorOccurred)


def test_recording_events_are_published(harness: Harness) -> None:
    harness.pipeline.start_recording(TriggerSource.MOUSE)
    harness.pipeline.stop_recording()

    assert harness.wait_idle()

    started = harness.of_type(RecordingStarted)
    finished = harness.of_type(RecordingFinished)
    assert started[0].source == "mouse"  # type: ignore[attr-defined]
    assert finished[0].duration_seconds == pytest.approx(1.0)  # type: ignore[attr-defined]


def test_protective_limit_is_passed_to_capture(harness: Harness) -> None:
    harness.settings.activation.max_record_seconds = 42

    harness.pipeline.start_recording(TriggerSource.TRAY)

    assert harness.capture.begin_calls == [42.0]


def test_language_follows_settings(harness: Harness) -> None:
    harness.settings.recognition.language_mode = "fixed"
    harness.settings.recognition.primary_language = "ru"
    transcriber = harness.registry.transcriber
    assert isinstance(transcriber, FakeTranscriber)

    harness.pipeline.start_recording(TriggerSource.TRAY)
    harness.pipeline.stop_recording()
    assert harness.wait_idle()

    assert transcriber.calls[-1][1] == "ru"


def test_auto_language_passes_none(harness: Harness) -> None:
    harness.settings.recognition.language_mode = "auto"
    transcriber = harness.registry.transcriber
    assert isinstance(transcriber, FakeTranscriber)

    harness.pipeline.start_recording(TriggerSource.TRAY)
    harness.pipeline.stop_recording()
    assert harness.wait_idle()

    assert transcriber.calls[-1][1] is None


# --------------------------------------------------------------------------- #
# Отказы и краевые случаи
# --------------------------------------------------------------------------- #


def test_start_is_rejected_without_microphone(harness: Harness) -> None:
    harness.capture.is_running = False

    assert harness.pipeline.start_recording(TriggerSource.HOTKEY) is False
    assert harness.state.state is AppState.IDLE
    errors = harness.of_type(ErrorOccurred)
    assert "Микрофон выключен" in errors[0].message  # type: ignore[attr-defined]


def test_start_is_ignored_while_busy(harness: Harness) -> None:
    harness.pipeline.start_recording(TriggerSource.HOTKEY)

    assert harness.pipeline.start_recording(TriggerSource.TRAY) is False
    assert len(harness.of_type(RecordingStarted)) == 1


def test_stop_without_recording_does_nothing(harness: Harness) -> None:
    harness.pipeline.stop_recording()

    assert harness.state.state is AppState.IDLE
    assert harness.of_type(RecordingFinished) == []


def test_empty_recording_returns_to_idle(harness: Harness) -> None:
    harness.capture.next_audio = np.zeros(0, dtype=np.float32)

    harness.pipeline.start_recording(TriggerSource.HOTKEY)
    harness.pipeline.stop_recording()

    assert harness.wait_idle()
    assert harness.of_type(TranscriptReady) == []


def test_missing_model_reports_error_and_recovers(harness: Harness) -> None:
    harness.registry.error = ModelNotReadyError("Модель не загружена")

    harness.pipeline.start_recording(TriggerSource.HOTKEY)
    harness.pipeline.stop_recording()

    assert wait_for(lambda: harness.state.state is AppState.ERROR)
    errors = harness.of_type(ErrorOccurred)
    assert "Модель не загружена" in errors[0].message  # type: ignore[attr-defined]


def test_unexpected_engine_failure_is_contained(harness: Harness) -> None:
    """Падение движка не должно оставлять конвейер в подвешенном состоянии."""
    harness.registry.transcriber = FakeTranscriber(raises=RuntimeError("segfault"))

    harness.pipeline.start_recording(TriggerSource.HOTKEY)
    harness.pipeline.stop_recording()

    assert wait_for(lambda: harness.state.state is AppState.ERROR)
    assert harness.of_type(ErrorOccurred)


def test_engine_substitution_is_announced(harness: Harness) -> None:
    harness.registry.note = "Движок заменён"

    harness.pipeline.start_recording(TriggerSource.HOTKEY)
    harness.pipeline.stop_recording()
    assert harness.wait_idle()

    notices = harness.of_type(NoticeIssued)
    assert any(n.message == "Движок заменён" for n in notices)  # type: ignore[attr-defined]


def test_truncated_recording_warns_the_user(harness: Harness) -> None:
    harness.capture.truncated = True

    harness.pipeline.start_recording(TriggerSource.HOTKEY)
    harness.pipeline.stop_recording()
    assert harness.wait_idle()

    notices = harness.of_type(NoticeIssued)
    assert any("предел длительности" in n.message for n in notices)  # type: ignore[attr-defined]


def test_cancel_discards_recording(harness: Harness) -> None:
    harness.pipeline.start_recording(TriggerSource.MOUSE)

    harness.pipeline.cancel_recording(reason="слишком короткое нажатие")

    assert harness.capture.cancelled is True
    assert harness.state.state is AppState.IDLE
    assert harness.of_type(TranscriptReady) == []
    finished = harness.of_type(RecordingFinished)
    assert finished[0].cancelled is True  # type: ignore[attr-defined]


def test_limit_watcher_stops_recording(harness: Harness) -> None:
    """Защитный лимит останавливает запись без участия пользователя."""
    harness.pipeline.start_recording(TriggerSource.HOTKEY)
    harness.capture.recording_limit_reached = True

    harness.capture.feed(np.zeros(512, dtype=np.float32))

    assert harness.wait_idle()
    assert harness.of_type(TranscriptReady)


def test_limit_watcher_is_detached_after_recording(harness: Harness) -> None:
    """Иначе с каждой записью копился бы лишний потребитель аудио."""
    for _ in range(3):
        harness.pipeline.start_recording(TriggerSource.HOTKEY)
        harness.pipeline.stop_recording()
        assert harness.wait_idle()

    assert harness.capture.consumer_count == 0


# --------------------------------------------------------------------------- #
# Режимы запуска
# --------------------------------------------------------------------------- #


def test_toggle_mode_starts_and_stops(harness: Harness) -> None:
    harness.settings.activation.stop_mode = "press_again"

    harness.pipeline.handle_press(TriggerSource.HOTKEY)
    assert harness.state.state is AppState.RECORDING

    harness.pipeline.handle_press(TriggerSource.HOTKEY)
    assert harness.wait_idle()
    assert harness.of_type(TranscriptReady)


def test_hold_mode_records_while_pressed(harness: Harness) -> None:
    harness.settings.activation.stop_mode = "hold"

    harness.pipeline.handle_press(TriggerSource.MOUSE)
    assert harness.state.state is AppState.RECORDING
    time.sleep(0.3)
    harness.pipeline.handle_release(TriggerSource.MOUSE)

    assert harness.wait_idle()
    assert harness.of_type(TranscriptReady)


def test_hold_mode_cancels_accidental_click(harness: Harness) -> None:
    harness.settings.activation.stop_mode = "hold"

    harness.pipeline.handle_press(TriggerSource.MOUSE)
    harness.pipeline.handle_release(TriggerSource.MOUSE)

    assert harness.wait_idle()
    assert harness.of_type(TranscriptReady) == []
    assert harness.capture.cancelled is True


def test_resting_state_is_listening_with_wake_word(harness: Harness) -> None:
    """При включённой голосовой активации конвейер возвращается к прослушиванию."""
    harness.settings.activation.wake_enabled = True

    harness.pipeline.start_recording(TriggerSource.VOICE)
    harness.pipeline.stop_recording()

    assert wait_for(lambda: harness.state.state is AppState.LISTENING)


def test_shutdown_is_safe_while_recording(harness: Harness) -> None:
    harness.pipeline.start_recording(TriggerSource.HOTKEY)

    harness.pipeline.shutdown()

    assert harness.registry.unload_calls == 1


# --------------------------------------------------------------------------- #
# Возврат прежнего буфера обмена
# --------------------------------------------------------------------------- #


def _run_once(harness: Harness) -> None:
    harness.pipeline.start_recording(TriggerSource.HOTKEY)
    harness.pipeline.stop_recording()
    assert harness.wait_idle()


def test_clipboard_restore_is_scheduled_when_enabled(harness: Harness) -> None:
    harness.settings.output.restore_clipboard = True
    harness.clipboard.text = "то, что было раньше"

    _run_once(harness)

    # Возврат отложен, а не выполнен сразу: пользователь ещё вставляет текст.
    assert harness.pipeline._clipboard_timer is not None
    assert harness.clipboard.text != "то, что было раньше"
    harness.pipeline.shutdown()


def test_clipboard_restore_is_not_scheduled_by_default(harness: Harness) -> None:
    harness.clipboard.text = "то, что было раньше"

    _run_once(harness)

    assert harness.pipeline._clipboard_timer is None


def test_scheduled_restore_returns_previous_text(harness: Harness) -> None:
    harness.settings.output.restore_clipboard = True
    harness.clipboard.text = "то, что было раньше"
    _run_once(harness)
    inserted = harness.clipboard.text or ""

    assert harness.pipeline.restore_clipboard(inserted, "то, что было раньше") is True
    assert harness.clipboard.text == "то, что было раньше"


def test_scheduled_restore_respects_manual_copy(harness: Harness) -> None:
    harness.settings.output.restore_clipboard = True
    harness.clipboard.text = "то, что было раньше"
    _run_once(harness)
    inserted = harness.clipboard.text or ""

    harness.clipboard.text = "скопировано вручную"

    assert harness.pipeline.restore_clipboard(inserted, "то, что было раньше") is False
    assert harness.clipboard.text == "скопировано вручную"


def test_shutdown_cancels_pending_restore(harness: Harness) -> None:
    harness.settings.output.restore_clipboard = True
    harness.clipboard.text = "то, что было раньше"
    _run_once(harness)

    harness.pipeline.shutdown()

    assert harness.pipeline._clipboard_timer is None
