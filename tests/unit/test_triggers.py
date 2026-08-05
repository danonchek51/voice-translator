"""Режимы запуска: Toggle и Hold."""

from __future__ import annotations

import pytest

from voiceflow.core.triggers import TriggerAction, TriggerCoordinator, TriggerSource


class Clock:
    """Управляемое время: без него тест удержания зависел бы от скорости машины."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class Recorder:
    """Подставная запись: коордиинатор спрашивает у неё текущее состояние."""

    def __init__(self) -> None:
        self.recording = False

    def __call__(self) -> bool:
        return self.recording


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


def make(mode: str, recorder: Recorder, clock: Clock) -> TriggerCoordinator:
    return TriggerCoordinator(
        mode_provider=lambda: mode,
        recording_provider=recorder,
        clock=clock,
        min_hold_seconds=0.25,
    )


# --------------------------------------------------------------------------- #
# Режим повторного нажатия
# --------------------------------------------------------------------------- #


def test_toggle_press_starts_then_stops(recorder: Recorder, clock: Clock) -> None:
    coordinator = make("press_again", recorder, clock)

    assert coordinator.press(TriggerSource.HOTKEY) is TriggerAction.START

    recorder.recording = True
    assert coordinator.press(TriggerSource.HOTKEY) is TriggerAction.STOP


def test_toggle_ignores_release(recorder: Recorder, clock: Clock) -> None:
    coordinator = make("press_again", recorder, clock)
    coordinator.press(TriggerSource.HOTKEY)
    recorder.recording = True

    assert coordinator.release(TriggerSource.HOTKEY) is TriggerAction.NONE


# --------------------------------------------------------------------------- #
# Режим удержания
# --------------------------------------------------------------------------- #


def test_hold_records_while_pressed(recorder: Recorder, clock: Clock) -> None:
    coordinator = make("hold", recorder, clock)

    assert coordinator.press(TriggerSource.MOUSE) is TriggerAction.START
    recorder.recording = True
    clock.advance(2.0)

    assert coordinator.release(TriggerSource.MOUSE) is TriggerAction.STOP


def test_hold_too_short_is_cancelled(recorder: Recorder, clock: Clock) -> None:
    """Случайный щелчок боковой кнопкой не должен запускать распознавание."""
    coordinator = make("hold", recorder, clock)
    coordinator.press(TriggerSource.MOUSE)
    recorder.recording = True
    clock.advance(0.1)

    assert coordinator.release(TriggerSource.MOUSE) is TriggerAction.CANCEL


def test_hold_boundary_counts_as_valid(recorder: Recorder, clock: Clock) -> None:
    coordinator = make("hold", recorder, clock)
    coordinator.press(TriggerSource.MOUSE)
    recorder.recording = True
    clock.advance(0.25)

    assert coordinator.release(TriggerSource.MOUSE) is TriggerAction.STOP


def test_hold_ignores_key_autorepeat(recorder: Recorder, clock: Clock) -> None:
    """Удерживаемая клавиша шлёт нажатия непрерывно — новая запись не нужна."""
    coordinator = make("hold", recorder, clock)
    coordinator.press(TriggerSource.HOTKEY)
    recorder.recording = True

    for _ in range(5):
        assert coordinator.press(TriggerSource.HOTKEY) is TriggerAction.NONE


def test_hold_release_from_other_source_is_ignored(
    recorder: Recorder, clock: Clock
) -> None:
    coordinator = make("hold", recorder, clock)
    coordinator.press(TriggerSource.MOUSE)
    recorder.recording = True
    clock.advance(1.0)

    assert coordinator.release(TriggerSource.HOTKEY) is TriggerAction.NONE
    assert coordinator.is_holding is True


def test_hold_release_without_recording_does_nothing(
    recorder: Recorder, clock: Clock
) -> None:
    """Запись успела завершиться сама по лимиту длительности."""
    coordinator = make("hold", recorder, clock)
    coordinator.press(TriggerSource.MOUSE)
    clock.advance(1.0)

    assert coordinator.release(TriggerSource.MOUSE) is TriggerAction.NONE


def test_hold_press_while_recording_does_nothing(
    recorder: Recorder, clock: Clock
) -> None:
    coordinator = make("hold", recorder, clock)
    recorder.recording = True

    assert coordinator.press(TriggerSource.MOUSE) is TriggerAction.NONE


# --------------------------------------------------------------------------- #
# Источники без удержания
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "source",
    [TriggerSource.TRAY, TriggerSource.OVERLAY, TriggerSource.VOICE],
)
def test_menu_and_overlay_always_toggle(
    source: TriggerSource, recorder: Recorder, clock: Clock
) -> None:
    """Пункт меню и голосовая фраза нельзя удерживать — всегда переключатель."""
    coordinator = make("hold", recorder, clock)

    assert coordinator.press(source) is TriggerAction.START
    recorder.recording = True
    assert coordinator.press(source) is TriggerAction.STOP
    assert coordinator.is_holding is False


def test_reset_clears_hold_state(recorder: Recorder, clock: Clock) -> None:
    coordinator = make("hold", recorder, clock)
    coordinator.press(TriggerSource.MOUSE)
    assert coordinator.is_holding is True

    coordinator.reset()

    assert coordinator.is_holding is False


def test_mode_change_takes_effect_immediately(recorder: Recorder, clock: Clock) -> None:
    mode = ["press_again"]
    coordinator = TriggerCoordinator(
        mode_provider=lambda: mode[0],
        recording_provider=recorder,
        clock=clock,
    )

    assert coordinator.press(TriggerSource.HOTKEY) is TriggerAction.START
    recorder.recording = True
    assert coordinator.release(TriggerSource.HOTKEY) is TriggerAction.NONE

    recorder.recording = False
    mode[0] = "hold"
    assert coordinator.press(TriggerSource.HOTKEY) is TriggerAction.START
    recorder.recording = True
    clock.advance(1.0)
    assert coordinator.release(TriggerSource.HOTKEY) is TriggerAction.STOP
