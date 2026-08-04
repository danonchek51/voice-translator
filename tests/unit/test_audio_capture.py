"""Захват микрофона с подставной звуковой подсистемой."""

from __future__ import annotations

import sys
import time
import types
from collections.abc import Callable

import numpy as np
import pytest

from voiceflow.core.audio import capture as capture_module
from voiceflow.core.audio.capture import AudioCapture
from voiceflow.core.audio.devices import AudioDevice, DeviceResolution
from voiceflow.core.events import (
    AudioDeviceChanged,
    AudioLevelChanged,
    ErrorOccurred,
    EventBus,
    NoticeIssued,
)

FAKE_DEVICE = AudioDevice(index=0, name="Подставной микрофон", channels=1, is_default=True)


class FakeStream:
    """Заменяет ``sounddevice.InputStream``: блоки подаём вручную."""

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.callback: Callable[..., None] = kwargs["callback"]  # type: ignore[assignment]
        self.started = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def close(self) -> None:
        self.closed = True

    def feed(self, block: np.ndarray) -> None:
        self.callback(block.reshape(-1, 1), block.size, None, None)


class FailingStream:
    def __init__(self, **kwargs: object) -> None:
        raise OSError("устройство занято")


@pytest.fixture
def fake_sounddevice(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    module = types.ModuleType("sounddevice")
    module.InputStream = FakeStream  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sounddevice", module)
    monkeypatch.setattr(
        capture_module,
        "resolve_device",
        lambda device_id, device_name: DeviceResolution(device=FAKE_DEVICE),
    )
    return module


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def audio(bus: EventBus, fake_sounddevice: types.ModuleType):  # type: ignore[no-untyped-def]
    capture = AudioCapture(bus, pre_roll_seconds=0.5)
    yield capture
    capture.stop()


def current_stream(capture: AudioCapture) -> FakeStream:
    stream = capture._stream
    assert isinstance(stream, FakeStream)
    return stream


def wait_for(predicate: Callable[[], bool], timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def tone(samples: int = 512, amplitude: float = 0.4) -> np.ndarray:
    t = np.arange(samples, dtype=np.float32)
    return (amplitude * np.sin(2 * np.pi * 440 * t / 16_000)).astype(np.float32)


def test_start_opens_stream_and_announces_device(audio: AudioCapture, bus: EventBus) -> None:
    events: list[AudioDeviceChanged] = []
    bus.subscribe(AudioDeviceChanged, events.append)

    assert audio.start() is True

    assert audio.is_running
    assert audio.device == FAKE_DEVICE
    assert current_stream(audio).started
    assert events[-1].active is True
    assert events[-1].device_name == FAKE_DEVICE.name


def test_start_is_idempotent(audio: AudioCapture) -> None:
    audio.start()
    first = current_stream(audio)

    audio.start()

    assert current_stream(audio) is first


def test_stream_uses_expected_format(audio: AudioCapture) -> None:
    audio.start()

    kwargs = current_stream(audio).kwargs

    assert kwargs["samplerate"] == 16_000
    assert kwargs["channels"] == 1
    assert kwargs["dtype"] == "float32"
    assert kwargs["blocksize"] == 512


def test_stop_closes_stream_and_resets_level(audio: AudioCapture, bus: EventBus) -> None:
    audio.start()
    stream = current_stream(audio)
    levels: list[AudioLevelChanged] = []
    bus.subscribe(AudioLevelChanged, levels.append)

    audio.stop(reason="проверка")

    assert stream.closed
    assert not audio.is_running
    assert levels[-1].rms == 0.0


def test_failure_to_open_reports_error(
    bus: EventBus, fake_sounddevice: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fake_sounddevice, "InputStream", FailingStream)
    errors: list[ErrorOccurred] = []
    bus.subscribe(ErrorOccurred, errors.append)
    capture = AudioCapture(bus)

    assert capture.start() is False

    assert not capture.is_running
    assert "устройство занято" in errors[-1].message
    assert errors[-1].recoverable is True


def test_missing_device_reports_error(
    bus: EventBus, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        capture_module,
        "resolve_device",
        lambda device_id, device_name: DeviceResolution(device=None, note="Микрофонов нет"),
    )
    errors: list[ErrorOccurred] = []
    bus.subscribe(ErrorOccurred, errors.append)

    assert AudioCapture(bus).start() is False
    assert errors[-1].message == "Микрофонов нет"


def test_device_substitution_is_announced(
    bus: EventBus, fake_sounddevice: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        capture_module,
        "resolve_device",
        lambda device_id, device_name: DeviceResolution(
            device=FAKE_DEVICE, note="Устройство заменено"
        ),
    )
    notices: list[NoticeIssued] = []
    bus.subscribe(NoticeIssued, notices.append)
    capture = AudioCapture(bus)

    capture.start()
    try:
        assert notices[-1].message == "Устройство заменено"
    finally:
        capture.stop()


def test_consumers_receive_blocks(audio: AudioCapture) -> None:
    received: list[np.ndarray] = []
    audio.add_consumer(received.append)
    audio.start()

    for _ in range(3):
        current_stream(audio).feed(tone())

    assert wait_for(lambda: len(received) == 3)
    assert all(block.shape == (512,) for block in received)


def test_unsubscribed_consumer_stops_receiving(audio: AudioCapture) -> None:
    received: list[np.ndarray] = []
    remove = audio.add_consumer(received.append)
    audio.start()

    current_stream(audio).feed(tone())
    assert wait_for(lambda: len(received) == 1)

    remove()
    current_stream(audio).feed(tone())
    time.sleep(0.1)

    assert len(received) == 1


def test_broken_consumer_does_not_stop_the_others(audio: AudioCapture) -> None:
    received: list[np.ndarray] = []

    def boom(block: np.ndarray) -> None:
        raise RuntimeError("потребитель сломался")

    audio.add_consumer(boom)
    audio.add_consumer(received.append)
    audio.start()

    current_stream(audio).feed(tone())

    assert wait_for(lambda: len(received) == 1)


def test_level_events_are_published(audio: AudioCapture, bus: EventBus) -> None:
    levels: list[AudioLevelChanged] = []
    bus.subscribe(AudioLevelChanged, levels.append)
    audio.start()

    for _ in range(5):
        current_stream(audio).feed(tone(amplitude=0.6))
        time.sleep(0.06)

    assert wait_for(lambda: any(event.rms > 0.0 for event in levels))


def test_recording_collects_audio(audio: AudioCapture) -> None:
    audio.start()
    audio.begin_recording(max_seconds=10.0, include_pre_roll=False)

    for _ in range(4):
        current_stream(audio).feed(tone())

    assert wait_for(lambda: audio.recording_seconds >= 4 * 512 / 16_000)
    result = audio.end_recording()

    assert result.audio.size == 4 * 512
    assert result.duration_seconds == pytest.approx(4 * 512 / 16_000)
    assert result.truncated is False
    assert not result.is_empty


def test_pre_roll_is_included(audio: AudioCapture) -> None:
    audio.start()
    stream = current_stream(audio)

    # Речь началась до нажатия: эти блоки попадут в запись из кольцевого буфера.
    for _ in range(3):
        stream.feed(tone())
    assert wait_for(lambda: True, timeout=0.1)

    audio.begin_recording(max_seconds=10.0, include_pre_roll=True)
    stream.feed(tone())

    assert wait_for(lambda: audio.recording_seconds > 3 * 512 / 16_000)
    result = audio.end_recording()

    assert result.audio.size >= 4 * 512


def test_protective_limit_truncates_recording(audio: AudioCapture) -> None:
    audio.start()
    # Лимит меньше одного блока округляется вверх до размера блока.
    audio.begin_recording(max_seconds=512 / 16_000, include_pre_roll=False)

    for _ in range(5):
        current_stream(audio).feed(tone())

    assert wait_for(lambda: audio.recording_limit_reached)
    result = audio.end_recording()

    assert result.truncated is True
    assert result.audio.size == 512


def test_cancel_recording_discards_audio(audio: AudioCapture) -> None:
    audio.start()
    audio.begin_recording(max_seconds=10.0, include_pre_roll=False)
    current_stream(audio).feed(tone())
    assert wait_for(lambda: audio.recording_seconds > 0)

    audio.cancel_recording()

    assert audio.is_recording is False
    assert audio.end_recording().is_empty


def test_blocks_are_ignored_when_not_recording(audio: AudioCapture) -> None:
    audio.start()

    current_stream(audio).feed(tone())
    time.sleep(0.1)

    assert audio.end_recording().is_empty


def test_restart_reopens_stream(audio: AudioCapture) -> None:
    audio.start()
    first = current_stream(audio)

    audio.restart()

    assert first.closed
    assert audio.is_running
    assert current_stream(audio) is not first


def test_gain_is_clamped(audio: AudioCapture) -> None:
    audio.set_gain(100.0)
    assert audio._gain == 10.0

    audio.set_gain(0.0)
    assert audio._gain == 0.1
