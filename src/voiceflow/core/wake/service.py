"""Сервис голосовой активации.

Слушает поток захвата, пропускает блоки через VAD и только при речи
передаёт короткий сегмент детектору команды. Во время записи, обработки
и вставки молчит.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

import numpy as np

from voiceflow.core.audio.vad import VoiceActivityDetector, create_vad
from voiceflow.core.events import ErrorOccurred, EventBus, WakeDebug
from voiceflow.core.settings.schema import ActivationSettings
from voiceflow.core.state import AppState, StateMachine
from voiceflow.core.wake.base import WakeHit, WakeWordDetector
from voiceflow.core.wake.matcher import phrases_match
from voiceflow.core.wake.registry import create_wake_detector

logger = logging.getLogger(__name__)

#: Сегмент речи для детектора, секунды.
SEGMENT_MIN_SECONDS = 0.35
SEGMENT_MAX_SECONDS = 2.0
#: Пауза до/после фразы, чтобы отсечь слитную речь.
EDGE_SILENCE_SECONDS = 0.2


class WakeService:
    """Подключается к AudioCapture как потребитель блоков."""

    def __init__(
        self,
        settings_provider: Callable[[], ActivationSettings],
        bus: EventBus,
        state: StateMachine,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        vad: VoiceActivityDetector | None = None,
        detector: WakeWordDetector | None = None,
        clock: Callable[[], float] = time.monotonic,
        debug: bool = False,
    ) -> None:
        self._settings_provider = settings_provider
        self._bus = bus
        self._state = state
        self._on_start = on_start
        self._on_stop = on_stop
        self._vad = vad or create_vad(threshold=0.35)
        self._detector = detector or create_wake_detector()
        self._clock = clock
        self._debug = debug

        self._lock = threading.RLock()
        self._enabled = False
        self._buffer = np.zeros(0, dtype=np.float32)
        self._speech_blocks = 0
        self._silence_blocks = 0
        self._in_speech = False
        self._last_fire = 0.0
        self._session_hits = 0
        self._sample_rate = 16_000
        self._block_seconds = 512 / 16_000

        self._apply_phrases()

    @property
    def detector(self) -> WakeWordDetector:
        return self._detector

    @property
    def session_hits(self) -> int:
        return self._session_hits

    def set_debug(self, enabled: bool) -> None:
        self._debug = enabled

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._enabled = enabled
            if enabled:
                self._apply_phrases()
                if self._state.state is AppState.IDLE:
                    try:
                        self._state.to(AppState.LISTENING)
                    except Exception:
                        pass
            else:
                self._reset_segment()
                if self._state.state is AppState.LISTENING:
                    try:
                        self._state.to(AppState.IDLE)
                    except Exception:
                        pass

    def reload_phrases(self) -> None:
        with self._lock:
            self._apply_phrases()

    def _apply_phrases(self) -> None:
        settings = self._settings_provider()
        phrases = [settings.wake_phrase]
        if settings.stop_mode in ("phrase", "same_phrase"):
            stop = (
                settings.wake_phrase
                if settings.stop_mode == "same_phrase"
                else settings.stop_phrase
            )
            if stop and stop not in phrases:
                phrases.append(stop)
        try:
            self._detector.set_phrases(phrases)
        except Exception:
            logger.exception("Не удалось обновить фразы детектора")
            self._bus.publish(
                ErrorOccurred(
                    source="wake",
                    message="Детектор голосовой команды недоступен",
                    recoverable=True,
                )
            )

    def on_audio(self, block: np.ndarray) -> None:
        """Точка входа для AudioCapture.add_consumer."""
        with self._lock:
            if not self._enabled:
                return
            settings = self._settings_provider()
            if not settings.wake_enabled:
                return
            state = self._state.state
            if state is AppState.PAUSED:
                self._reset_segment()
                return
            if state is AppState.RECORDING:
                # Во время записи слушаем только стоп-фразу.
                if settings.stop_mode not in ("phrase", "same_phrase"):
                    return
            elif state in (
                AppState.TRANSCRIBING,
                AppState.PROCESSING,
                AppState.PASTING,
                AppState.ERROR,
            ):
                self._reset_segment()
                return
            elif state not in (AppState.IDLE, AppState.LISTENING):
                return

            speech = self._vad.is_speech(block)
            if speech:
                if not self._in_speech:
                    self._in_speech = True
                    self._buffer = np.zeros(0, dtype=np.float32)
                self._speech_blocks += 1
                self._silence_blocks = 0
                self._buffer = np.concatenate(
                    [self._buffer, np.asarray(block, dtype=np.float32).reshape(-1)]
                )
                max_samples = int(SEGMENT_MAX_SECONDS * self._sample_rate)
                if self._buffer.size >= max_samples:
                    self._evaluate_segment(settings, force=True)
            else:
                self._silence_blocks += 1
                if self._in_speech:
                    if self._silence_blocks * self._block_seconds >= EDGE_SILENCE_SECONDS:
                        self._evaluate_segment(settings, force=False)
                        self._reset_segment()

    def _evaluate_segment(self, settings: ActivationSettings, force: bool) -> None:
        duration = self._buffer.size / self._sample_rate
        if duration < SEGMENT_MIN_SECONDS and not force:
            return
        if duration < 0.2:
            return

        now = self._clock()
        if (now - self._last_fire) * 1000 < settings.cooldown_ms:
            logger.debug("Кулдаун детектора, пропуск")
            return

        try:
            hit = self._detector.process(self._buffer, self._sample_rate)
        except Exception:
            logger.exception("Сбой детектора команды")
            return

        if hit is None:
            if self._debug:
                self._bus.publish(WakeDebug(text="", score=0.0, matched=False, engine=""))
            return

        self._handle_hit(hit, settings)

    def _handle_hit(self, hit: WakeHit, settings: ActivationSettings) -> None:
        recording = self._state.state is AppState.RECORDING
        matched_start = phrases_match(hit.text, settings.wake_phrase, settings.sensitivity)
        stop_phrase = (
            settings.wake_phrase
            if settings.stop_mode == "same_phrase"
            else settings.stop_phrase
        )
        matched_stop = phrases_match(hit.text, stop_phrase, settings.sensitivity)

        if self._debug:
            self._bus.publish(
                WakeDebug(
                    text=hit.text,
                    score=hit.score,
                    matched=matched_start or matched_stop,
                    engine=hit.engine,
                )
            )

        # В лог идёт только событие и score, без сохранения текста как истории.
        logger.info(
            "Детектор %s: score=%.2f matched_start=%s matched_stop=%s",
            hit.engine,
            hit.score,
            matched_start,
            matched_stop,
        )

        if recording and settings.stop_mode in ("phrase", "same_phrase") and matched_stop:
            self._last_fire = self._clock()
            self._session_hits += 1
            self._on_stop()
            return

        if not recording and matched_start:
            self._last_fire = self._clock()
            self._session_hits += 1
            self._on_start()
            return

    def _reset_segment(self) -> None:
        self._buffer = np.zeros(0, dtype=np.float32)
        self._speech_blocks = 0
        self._in_speech = False
        self._vad.reset()
        self._detector.reset()

    def close(self) -> None:
        with self._lock:
            self._enabled = False
            self._detector.close()
