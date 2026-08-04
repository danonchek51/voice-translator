"""Оркестратор: от нажатия до готового текста.

Держит порядок шагов и состояние. Каждый шаг вынесен в отдельную подсистему,
поэтому замена модели или добавление режима обработки конвейер не меняет.

Тяжёлые шаги выполняются в фоновом потоке: интерфейс не должен замирать
на время распознавания.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

import numpy as np

from voiceflow.core.asr.base import TranscriberError, TranscriptResult
from voiceflow.core.asr.registry import TranscriberRegistry
from voiceflow.core.audio.capture import AudioCapture
from voiceflow.core.delivery import ResultDelivery
from voiceflow.core.diagnostics.logging import log_user_text
from voiceflow.core.events import (
    ErrorOccurred,
    EventBus,
    NoticeIssued,
    RecordingFinished,
    RecordingStarted,
    ResultDelivered,
    TextProcessed,
    TranscriptReady,
)
from voiceflow.core.settings.schema import Settings
from voiceflow.core.state import AppState, StateMachine
from voiceflow.core.text.modes import ProcessingStep, enabled_steps
from voiceflow.core.text.processor import TextProcessor
from voiceflow.core.triggers import TriggerAction, TriggerCoordinator, TriggerSource
from voiceflow.platform.base import WindowInfo

logger = logging.getLogger(__name__)

#: Через столько секунд плашка сама уходит из состояния ошибки.
ERROR_RESET_SECONDS = 5.0

#: Через столько секунд после вставки возвращается прежнее содержимое буфера.
#: Меньше — пользователь не успеет вставить повторно, больше — забудет, что
#: копировал раньше.
RESTORE_CLIPBOARD_SECONDS = 10.0


class Pipeline:
    """Владелец сценария «нажал — сказал — получил текст»."""

    def __init__(
        self,
        settings_provider: Callable[[], Settings],
        bus: EventBus,
        state: StateMachine,
        capture: AudioCapture,
        transcribers: TranscriberRegistry,
        delivery: ResultDelivery,
        processor: TextProcessor,
    ) -> None:
        self._settings_provider = settings_provider
        self._bus = bus
        self._state = state
        self._capture = capture
        self._transcribers = transcribers
        self._delivery = delivery
        self._processor = processor
        self._lock = threading.RLock()
        self._worker: threading.Thread | None = None
        self._error_timer: threading.Timer | None = None
        self._clipboard_timer: threading.Timer | None = None
        self._limit_watcher_remove: Callable[[], None] | None = None
        self._target: WindowInfo | None = None

        self._coordinator = TriggerCoordinator(
            mode_provider=lambda: self._settings().activation.stop_mode,
            recording_provider=lambda: self._capture.is_recording,
        )

    def _settings(self) -> Settings:
        return self._settings_provider()

    # ------------------------------------------------------------------ #
    # Внешний интерфейс: нажатия
    # ------------------------------------------------------------------ #

    def handle_press(self, source: TriggerSource) -> None:
        self._apply(self._coordinator.press(source), source)

    def handle_release(self, source: TriggerSource) -> None:
        self._apply(self._coordinator.release(source), source)

    def _apply(self, action: TriggerAction, source: TriggerSource) -> None:
        if action is TriggerAction.START:
            self.start_recording(source)
        elif action is TriggerAction.STOP:
            self.stop_recording()
        elif action is TriggerAction.CANCEL:
            self.cancel_recording(reason="слишком короткое нажатие")

    # ------------------------------------------------------------------ #
    # Запись
    # ------------------------------------------------------------------ #

    def start_recording(self, source: TriggerSource) -> bool:
        """Начинает запись. ``False`` — сейчас нельзя."""
        with self._lock:
            if self._state.is_busy:
                logger.debug("Запуск проигнорирован: конвейер занят")
                return False
            if not self._capture.is_running:
                self._bus.publish(
                    ErrorOccurred(
                        source="pipeline",
                        message="Микрофон выключен. Снимите паузу прослушивания.",
                    )
                )
                return False

            self._cancel_error_timer()
            # Окно запоминается сейчас, а не после обработки: пользователь
            # может переключиться, пока идёт распознавание.
            self._target = self._delivery.capture_target()
            activation = self._settings().activation
            self._capture.begin_recording(max_seconds=float(activation.max_record_seconds))
            self._limit_watcher_remove = self._capture.add_consumer(self._watch_limit)
            self._state.to(AppState.RECORDING, detail="")

        self._bus.publish(RecordingStarted(source=source.value))
        logger.info("Запись начата (%s)", source.value)
        return True

    def stop_recording(self) -> None:
        """Останавливает запись и запускает распознавание в фоне."""
        with self._lock:
            if not self._capture.is_recording:
                return
            self._detach_limit_watcher()
            result = self._capture.end_recording()
            self._state.to(AppState.TRANSCRIBING)

        self._bus.publish(
            RecordingFinished(
                duration_seconds=result.duration_seconds,
                truncated=result.truncated,
            )
        )
        if result.truncated:
            self._bus.publish(
                NoticeIssued(
                    source="pipeline",
                    message="Достигнут предел длительности записи, запись остановлена",
                )
            )
        if result.dropped_blocks:
            logger.warning(
                "Потеряно блоков аудио из-за перегрузки: %s", result.dropped_blocks
            )

        if result.is_empty:
            self._finish(detail="пустая запись")
            return

        self._run_in_background(
            lambda: self._transcribe(result.audio, result.sample_rate)
        )

    def cancel_recording(self, reason: str = "") -> None:
        """Прерывает запись без обработки."""
        with self._lock:
            if not self._capture.is_recording:
                return
            self._detach_limit_watcher()
            self._capture.cancel_recording()
            self._target = None
        self._bus.publish(RecordingFinished(duration_seconds=0.0, cancelled=True))
        logger.info("Запись отменена%s", f": {reason}" if reason else "")
        self._finish(detail=reason)

    def _watch_limit(self, _block: np.ndarray) -> None:
        """Останавливает запись, когда сработал защитный лимит длительности."""
        if self._capture.recording_limit_reached:
            self.stop_recording()

    def _detach_limit_watcher(self) -> None:
        remove = self._limit_watcher_remove
        self._limit_watcher_remove = None
        if remove is not None:
            remove()

    # ------------------------------------------------------------------ #
    # Распознавание
    # ------------------------------------------------------------------ #

    def _transcribe(self, audio: np.ndarray, sample_rate: int) -> None:
        try:
            resolved = self._transcribers.resolve()
        except TranscriberError as exc:
            self._fail("asr", str(exc))
            return

        if resolved.note:
            self._bus.publish(NoticeIssued(source="asr", message=resolved.note))

        recognition = self._settings().recognition
        language = (
            None if recognition.language_mode == "auto" else recognition.primary_language
        )

        try:
            result = resolved.transcriber.transcribe(
                audio,
                sample_rate=sample_rate,
                language=language,
            )
        except TranscriberError as exc:
            self._fail("asr", str(exc))
            return
        except Exception:
            logger.exception("Непредвиденная ошибка распознавания")
            self._fail("asr", "Непредвиденная ошибка распознавания, подробности в логе")
            return

        self._publish_transcript(result)

    def _publish_transcript(self, result: TranscriptResult) -> None:
        logger.info(
            "Распознано за %.2f с (%.1fx реального времени), движок %s",
            result.elapsed_seconds,
            result.speed_ratio,
            result.engine,
        )
        log_user_text(logger, "Сырой текст", result.text)

        self._bus.publish(
            TranscriptReady(
                text=result.text,
                language=result.language,
                engine=result.engine,
                model_id=result.model_id,
                audio_seconds=result.audio_seconds,
                elapsed_seconds=result.elapsed_seconds,
                empty_reason=result.empty_reason,
            )
        )

        if result.is_empty:
            self._finish(detail=result.empty_reason)
            return

        self._process(result.text)

    # ------------------------------------------------------------------ #
    # Обработка текста
    # ------------------------------------------------------------------ #

    @property
    def steps(self) -> tuple[str, ...]:
        """Шаги обработки, включённые прямо сейчас."""
        return tuple(step.id for step in enabled_steps(self._settings().processing))

    def _announce_step(self, step: ProcessingStep) -> None:
        """Меняет подпись на плашке: «Очищаю», «Перевожу», «Формулирую»."""
        try:
            self._state.to(AppState.PROCESSING, detail=step.id)
        except Exception:
            logger.debug("Не удалось обновить подпись шага «%s»", step.id)

    def _process(self, raw: str) -> None:
        first = self.steps[0] if self.steps else ""
        try:
            # Шаг передаётся как пояснение: плашка показывает «Перевожу»
            # вместо общего «Очищаю», не заводя отдельных состояний.
            self._state.to(AppState.PROCESSING, detail=first)
        except Exception:
            logger.exception("Не удалось перейти к обработке текста")

        try:
            processed = self._processor.process(raw, on_step=self._announce_step)
        except Exception:
            logger.exception("Сбой обработки текста, отдаю сырой транскрипт")
            self._bus.publish(
                NoticeIssued(
                    source="text",
                    message="Обработка текста не удалась, вставляю распознанный текст",
                )
            )
            self._deliver(raw)
            return

        log_user_text(logger, "Обработанный текст", processed.text)
        self._bus.publish(
            TextProcessed(
                raw=raw,
                cleaned=processed.cleaned,
                final=processed.text,
                steps=processed.steps,
                used_llm=processed.used_llm,
                fallback_reason=processed.fallback_reason,
            )
        )
        if processed.fallback_reason:
            logger.info("Обработка без языковой модели: %s", processed.fallback_reason)

        # Пустой результат обработки — повод отдать хотя бы сырой текст,
        # иначе пользователь потеряет сказанное.
        self._deliver(processed.text or raw)

    # ------------------------------------------------------------------ #
    # Доставка результата
    # ------------------------------------------------------------------ #

    def _deliver(self, text: str) -> None:
        target = self._target
        self._target = None
        try:
            self._state.to(AppState.PASTING)
        except Exception:
            logger.exception("Не удалось перейти к вставке")

        outcome = self._delivery.deliver(text, target)

        self._bus.publish(
            ResultDelivered(
                text=text,
                copied=outcome.copied,
                pasted=outcome.pasted,
                message=outcome.message,
                target=target.label() if target else "",
            )
        )

        if not outcome.copied:
            self._fail("output", outcome.message)
            return

        if outcome.previous_clipboard is not None:
            self._schedule_clipboard_restore(text, outcome.previous_clipboard)

        logger.info("Доставка: %s", outcome.message)
        self._finish(detail="" if outcome.pasted else outcome.message)

    # ------------------------------------------------------------------ #
    # Возврат прежнего буфера обмена
    # ------------------------------------------------------------------ #

    def _schedule_clipboard_restore(self, inserted: str, previous: str) -> None:
        """Откладывает возврат буфера: сразу нельзя, пользователь ещё вставляет."""
        self._cancel_clipboard_timer()
        timer = threading.Timer(
            RESTORE_CLIPBOARD_SECONDS,
            self.restore_clipboard,
            args=(inserted, previous),
        )
        timer.daemon = True
        with self._lock:
            self._clipboard_timer = timer
        timer.start()

    def restore_clipboard(self, inserted: str, previous: str) -> bool:
        """Возвращает прежний буфер, если пользователь его не занял своим."""
        with self._lock:
            self._clipboard_timer = None
        restored = self._delivery.restore_clipboard(previous, expected=inserted)
        if restored:
            logger.info("Прежнее содержимое буфера обмена возвращено")
        return restored

    def _cancel_clipboard_timer(self) -> None:
        with self._lock:
            timer = self._clipboard_timer
            self._clipboard_timer = None
        if timer is not None:
            timer.cancel()

    # ------------------------------------------------------------------ #
    # Завершение и ошибки
    # ------------------------------------------------------------------ #

    def _resting_state(self) -> AppState:
        """Куда возвращаться после работы."""
        activation = self._settings().activation
        if activation.wake_enabled and self._capture.is_running:
            return AppState.LISTENING
        return AppState.IDLE

    def _finish(self, detail: str = "") -> None:
        target = self._resting_state()
        if self._state.state is target:
            return
        try:
            self._state.to(target, detail=detail)
        except Exception:
            logger.exception("Не удалось вернуться в состояние покоя")
            self._state.reset(detail=detail)

    def _fail(self, source: str, message: str) -> None:
        logger.error("%s: %s", source, message)
        self._bus.publish(ErrorOccurred(source=source, message=message))
        self._state.to(AppState.ERROR, detail=message)
        self._schedule_error_reset()

    def _schedule_error_reset(self) -> None:
        self._cancel_error_timer()
        timer = threading.Timer(ERROR_RESET_SECONDS, self._clear_error)
        timer.daemon = True
        self._error_timer = timer
        timer.start()

    def _cancel_error_timer(self) -> None:
        timer = self._error_timer
        self._error_timer = None
        if timer is not None:
            timer.cancel()

    def _clear_error(self) -> None:
        self._error_timer = None
        if self._state.state is AppState.ERROR:
            self._finish()

    # ------------------------------------------------------------------ #
    # Фоновая работа
    # ------------------------------------------------------------------ #

    def _run_in_background(self, work: Callable[[], None]) -> None:
        def runner() -> None:
            try:
                work()
            except Exception:
                logger.exception("Сбой фонового шага конвейера")
                self._fail("pipeline", "Сбой обработки, подробности в логе")

        worker = threading.Thread(target=runner, name="voiceflow-pipeline", daemon=True)
        self._worker = worker
        worker.start()

    def shutdown(self) -> None:
        self._cancel_error_timer()
        self._cancel_clipboard_timer()
        self._detach_limit_watcher()
        self._coordinator.reset()
        worker = self._worker
        if worker is not None and worker.is_alive():
            worker.join(timeout=3.0)
        self._transcribers.unload_all()
