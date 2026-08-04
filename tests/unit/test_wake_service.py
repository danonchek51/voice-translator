"""Сервис голосовой активации с подставным детектором."""

from __future__ import annotations

import numpy as np

from voiceflow.core.audio.vad import EnergyVad
from voiceflow.core.events import EventBus, WakeDebug
from voiceflow.core.settings.schema import ActivationSettings
from voiceflow.core.state import AppState, StateMachine
from voiceflow.core.wake.base import DetectorInfo, WakeHit, WakeWordDetector
from voiceflow.core.wake.service import WakeService


class FakeVad(EnergyVad):
    def __init__(self, speech: bool = True) -> None:
        super().__init__(threshold=0.0)
        self.speech = speech

    def is_speech(self, block: np.ndarray) -> bool:
        return self.speech


class FakeDetector(WakeWordDetector):
    engine = "fake"

    def __init__(self) -> None:
        self.phrases: list[str] = []
        self.next_hit: WakeHit | None = None

    def info(self) -> DetectorInfo:
        return DetectorInfo(engine=self.engine, title="fake", ready=True)

    def is_available(self) -> bool:
        return True

    def set_phrases(self, phrases: list[str]) -> None:
        self.phrases = list(phrases)

    def process(self, audio: np.ndarray, sample_rate: int) -> WakeHit | None:
        return self.next_hit


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _settings(**kwargs: object) -> ActivationSettings:
    base = ActivationSettings(wake_enabled=True, wake_phrase="слушай сюда", cooldown_ms=0)
    for key, value in kwargs.items():
        setattr(base, key, value)
    return base


def test_wake_starts_recording_on_phrase() -> None:
    bus = EventBus()
    state = StateMachine(AppState.LISTENING)
    started: list[bool] = []
    stopped: list[bool] = []
    detector = FakeDetector()
    detector.next_hit = WakeHit(text="слушай сюда", score=1.0, engine="fake")
    clock = Clock()
    vad = FakeVad(True)

    service = WakeService(
        settings_provider=lambda: _settings(),
        bus=bus,
        state=state,
        on_start=lambda: started.append(True),
        on_stop=lambda: stopped.append(True),
        vad=vad,
        detector=detector,
        clock=clock,
    )
    service.set_enabled(True)

    # Набираем сегмент речи длиннее минимума и завершаем тишиной.
    loud = np.ones(512, dtype=np.float32) * 0.2
    silence = np.zeros(512, dtype=np.float32)
    for _ in range(25):  # ~0.8 с
        service.on_audio(loud)
    vad.speech = False
    for _ in range(12):  # тишина после фразы
        service.on_audio(silence)

    assert started == [True]
    assert stopped == []


def test_stop_phrase_during_recording() -> None:
    bus = EventBus()
    state = StateMachine(AppState.RECORDING)
    started: list[bool] = []
    stopped: list[bool] = []
    detector = FakeDetector()
    detector.next_hit = WakeHit(text="конец записи", score=1.0, engine="fake")
    vad = FakeVad(True)

    service = WakeService(
        settings_provider=lambda: _settings(stop_mode="phrase", stop_phrase="конец записи"),
        bus=bus,
        state=state,
        on_start=lambda: started.append(True),
        on_stop=lambda: stopped.append(True),
        vad=vad,
        detector=detector,
        clock=Clock(),
    )
    service.set_enabled(True)

    loud = np.ones(512, dtype=np.float32) * 0.2
    silence = np.zeros(512, dtype=np.float32)
    for _ in range(25):
        service.on_audio(loud)
    vad.speech = False
    for _ in range(12):
        service.on_audio(silence)

    assert stopped == [True]
    assert started == []


def test_debug_event_published() -> None:
    bus = EventBus()
    events: list[WakeDebug] = []
    bus.subscribe(WakeDebug, events.append)
    state = StateMachine(AppState.LISTENING)
    detector = FakeDetector()
    detector.next_hit = WakeHit(text="слушай сюда", score=0.9, engine="fake")
    vad = FakeVad(True)

    service = WakeService(
        settings_provider=lambda: _settings(),
        bus=bus,
        state=state,
        on_start=lambda: None,
        on_stop=lambda: None,
        vad=vad,
        detector=detector,
        clock=Clock(),
        debug=True,
    )
    service.set_enabled(True)

    loud = np.ones(512, dtype=np.float32) * 0.2
    silence = np.zeros(512, dtype=np.float32)
    for _ in range(25):
        service.on_audio(loud)
    vad.speech = False
    for _ in range(12):
        service.on_audio(silence)

    assert events
    assert events[0].matched is True
