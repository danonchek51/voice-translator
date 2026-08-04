"""Машина состояний."""

from __future__ import annotations

import pytest

from voiceflow.core.state import (
    STATE_LABELS,
    AppState,
    InvalidTransitionError,
    StateMachine,
)


def test_starts_idle() -> None:
    assert StateMachine().state is AppState.IDLE


def test_happy_path_transitions() -> None:
    machine = StateMachine()
    chain = [
        AppState.LISTENING,
        AppState.RECORDING,
        AppState.TRANSCRIBING,
        AppState.PROCESSING,
        AppState.PASTING,
        AppState.IDLE,
    ]

    for target in chain:
        assert machine.to(target) is True
        assert machine.state is target


def test_forbidden_transition_raises() -> None:
    machine = StateMachine()

    with pytest.raises(InvalidTransitionError):
        machine.to(AppState.PASTING)

    assert machine.state is AppState.IDLE


def test_error_and_pause_reachable_from_anywhere() -> None:
    for state in AppState:
        machine = StateMachine(initial=state)
        assert machine.can(AppState.ERROR)
        assert machine.can(AppState.PAUSED)


def test_same_state_is_noop() -> None:
    machine = StateMachine()
    calls: list[tuple[AppState, AppState, str]] = []
    machine.add_listener(lambda old, new, detail: calls.append((old, new, detail)))

    assert machine.to(AppState.IDLE) is False
    assert calls == []


def test_listener_receives_transition() -> None:
    machine = StateMachine()
    calls: list[tuple[AppState, AppState, str]] = []
    machine.add_listener(lambda old, new, detail: calls.append((old, new, detail)))

    machine.to(AppState.RECORDING, detail="горячая клавиша")

    assert calls == [(AppState.IDLE, AppState.RECORDING, "горячая клавиша")]


def test_broken_listener_does_not_block_others() -> None:
    machine = StateMachine()
    seen: list[AppState] = []

    def boom(old: AppState, new: AppState, detail: str) -> None:
        raise RuntimeError("подписчик сломался")

    machine.add_listener(boom)
    machine.add_listener(lambda old, new, detail: seen.append(new))

    machine.to(AppState.LISTENING)

    assert seen == [AppState.LISTENING]


def test_reset_returns_to_idle_from_any_state() -> None:
    machine = StateMachine(initial=AppState.PASTING)
    seen: list[tuple[AppState, AppState]] = []
    machine.add_listener(lambda old, new, detail: seen.append((old, new)))

    assert machine.reset(detail="сбой") is True
    assert machine.state is AppState.IDLE
    assert seen == [(AppState.PASTING, AppState.IDLE)]
    assert machine.reset() is False


def test_is_busy_covers_working_states() -> None:
    busy = {
        AppState.RECORDING,
        AppState.TRANSCRIBING,
        AppState.PROCESSING,
        AppState.PASTING,
    }
    for state in AppState:
        assert StateMachine(initial=state).is_busy is (state in busy)


def test_every_state_has_a_label() -> None:
    assert set(STATE_LABELS) == set(AppState)
    assert all(label.strip() for label in STATE_LABELS.values())
