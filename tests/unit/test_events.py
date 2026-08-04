"""Шина событий."""

from __future__ import annotations

import threading

from voiceflow.core.events import (
    AudioLevelChanged,
    ErrorOccurred,
    Event,
    EventBus,
    StateChanged,
)
from voiceflow.core.state import AppState


def test_handler_receives_its_event_type() -> None:
    bus = EventBus()
    received: list[AudioLevelChanged] = []
    bus.subscribe(AudioLevelChanged, received.append)

    bus.publish(AudioLevelChanged(rms=0.5, peak=0.9))

    assert len(received) == 1
    assert received[0].rms == 0.5


def test_handler_does_not_receive_other_types() -> None:
    bus = EventBus()
    received: list[AudioLevelChanged] = []
    bus.subscribe(AudioLevelChanged, received.append)

    bus.publish(ErrorOccurred(source="asr", message="нет модели"))

    assert received == []


def test_base_type_subscription_receives_everything() -> None:
    bus = EventBus()
    received: list[Event] = []
    bus.subscribe(Event, received.append)

    bus.publish(AudioLevelChanged(rms=0.1, peak=0.2))
    bus.publish(StateChanged(old=AppState.IDLE, new=AppState.RECORDING))

    assert len(received) == 2


def test_unsubscribe_stops_delivery() -> None:
    bus = EventBus()
    received: list[ErrorOccurred] = []
    unsubscribe = bus.subscribe(ErrorOccurred, received.append)

    bus.publish(ErrorOccurred(source="a", message="раз"))
    unsubscribe()
    bus.publish(ErrorOccurred(source="a", message="два"))

    assert len(received) == 1


def test_unsubscribe_twice_is_safe() -> None:
    bus = EventBus()
    unsubscribe = bus.subscribe(ErrorOccurred, lambda event: None)

    unsubscribe()
    unsubscribe()


def test_broken_handler_does_not_stop_others() -> None:
    bus = EventBus()
    received: list[ErrorOccurred] = []

    def boom(event: ErrorOccurred) -> None:
        raise RuntimeError("обработчик сломался")

    bus.subscribe(ErrorOccurred, boom)
    bus.subscribe(ErrorOccurred, received.append)

    bus.publish(ErrorOccurred(source="a", message="текст"))

    assert len(received) == 1


def test_publish_from_many_threads() -> None:
    bus = EventBus()
    received: list[AudioLevelChanged] = []
    lock = threading.Lock()

    def collect(event: AudioLevelChanged) -> None:
        with lock:
            received.append(event)

    bus.subscribe(AudioLevelChanged, collect)

    def worker() -> None:
        for _ in range(100):
            bus.publish(AudioLevelChanged(rms=0.1, peak=0.2))

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(received) == 400


def test_clear_removes_all_subscriptions() -> None:
    bus = EventBus()
    received: list[ErrorOccurred] = []
    bus.subscribe(ErrorOccurred, received.append)

    bus.clear()
    bus.publish(ErrorOccurred(source="a", message="текст"))

    assert received == []


def test_events_are_immutable() -> None:
    event = AudioLevelChanged(rms=0.1, peak=0.2)
    try:
        event.rms = 0.9  # type: ignore[misc]
    except (AttributeError, TypeError):
        return
    raise AssertionError("событие должно быть неизменяемым")
