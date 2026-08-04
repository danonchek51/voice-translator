"""Единый поток захвата микрофона.

Один открытый поток на всё приложение: его данные получают и измеритель
уровня, и кольцевой буфер pre-roll, и — на следующих этапах — детектор
голосовой команды и запись основной речи.

Разделение потоков выполнения:

* callback PortAudio (высокий приоритет) делает минимум: пишет в кольцевой
  буфер, считает уровень и кладёт блок в очередь;
* рабочий поток (обычный приоритет) разбирает очередь, кормит потребителей
  и публикует события.

Так тяжёлый потребитель не может вызвать треск и потерю блоков.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from voiceflow.core.audio.devices import AudioDevice, resolve_device
from voiceflow.core.audio.level import LevelMeter, LevelReading
from voiceflow.core.audio.ring_buffer import RingBuffer
from voiceflow.core.events import (
    AudioDeviceChanged,
    AudioLevelChanged,
    ErrorOccurred,
    EventBus,
    NoticeIssued,
)

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
#: 32 мс при 16 кГц. Столько же ожидает Silero VAD.
BLOCK_SIZE = 512
BLOCK_MS = BLOCK_SIZE * 1000 // SAMPLE_RATE

#: Не чаще 20 обновлений полоски громкости в секунду.
LEVEL_PUBLISH_INTERVAL_MS = 50

#: Пределы очереди: примерно две секунды. Дальше блоки отбрасываются,
#: чтобы медленный потребитель не съел память.
QUEUE_MAX_BLOCKS = 64

PRE_ROLL_SECONDS = 2.0

#: Потребитель блоков аудио. Вызывается в рабочем потоке.
Consumer = Callable[[np.ndarray], None]


@dataclass(slots=True)
class RecordingResult:
    """Итог записи основной речи."""

    audio: np.ndarray
    sample_rate: int
    duration_seconds: float
    #: Запись остановлена защитным лимитом длительности, а не пользователем.
    truncated: bool = False
    #: Блоки, потерянные из-за переполнения очереди. Ноль — норма.
    dropped_blocks: int = 0

    @property
    def is_empty(self) -> bool:
        return self.audio.size == 0


class AudioCapture:
    """Владелец потока захвата."""

    def __init__(
        self,
        bus: EventBus,
        sample_rate: int = SAMPLE_RATE,
        block_size: int = BLOCK_SIZE,
        pre_roll_seconds: float = PRE_ROLL_SECONDS,
    ) -> None:
        self._bus = bus
        self._sample_rate = sample_rate
        self._block_size = block_size

        self._ring = RingBuffer.for_seconds(pre_roll_seconds, sample_rate)
        self._meter = LevelMeter()
        self._gain = 1.0

        self._lock = threading.RLock()
        self._stream: object | None = None
        self._device: AudioDevice | None = None

        self._queue: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=QUEUE_MAX_BLOCKS)
        self._worker: threading.Thread | None = None
        self._worker_stop = threading.Event()

        self._consumers: list[Consumer] = []
        self._consumers_lock = threading.RLock()

        self._recording = False
        self._recorded: list[np.ndarray] = []
        self._recorded_samples = 0
        self._record_limit_samples = 0
        self._record_truncated = False
        self._dropped_blocks = 0

        self._last_level_publish_ms = 0.0

    # ------------------------------------------------------------------ #
    # Свойства
    # ------------------------------------------------------------------ #

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def block_size(self) -> int:
        return self._block_size

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._stream is not None

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._recording

    @property
    def device(self) -> AudioDevice | None:
        with self._lock:
            return self._device

    @property
    def level(self) -> LevelReading:
        return self._meter.current

    def set_gain(self, gain: float) -> None:
        self._gain = max(0.1, min(10.0, gain))

    # ------------------------------------------------------------------ #
    # Потребители
    # ------------------------------------------------------------------ #

    def add_consumer(self, consumer: Consumer) -> Callable[[], None]:
        """Регистрирует потребителя блоков и возвращает функцию отписки."""
        with self._consumers_lock:
            self._consumers.append(consumer)

        def remove() -> None:
            with self._consumers_lock:
                if consumer in self._consumers:
                    self._consumers.remove(consumer)

        return remove

    # ------------------------------------------------------------------ #
    # Запуск и остановка
    # ------------------------------------------------------------------ #

    def start(self, device_id: int | None = None, device_name: str = "") -> bool:
        """Открывает поток захвата. Возвращает ``False`` при неудаче."""
        with self._lock:
            if self._stream is not None:
                return True

            resolution = resolve_device(device_id, device_name)
            if resolution.device is None:
                self._bus.publish(
                    ErrorOccurred(
                        source="audio",
                        message=resolution.note or "Микрофон не найден",
                        recoverable=True,
                    )
                )
                return False
            if resolution.note:
                self._bus.publish(NoticeIssued(source="audio", message=resolution.note))

            try:
                import sounddevice as sd

                stream = sd.InputStream(
                    samplerate=self._sample_rate,
                    blocksize=self._block_size,
                    channels=1,
                    dtype="float32",
                    device=resolution.device.index,
                    callback=self._audio_callback,
                )
                stream.start()
            except Exception as exc:
                logger.exception("Не удалось открыть микрофон")
                self._bus.publish(
                    ErrorOccurred(
                        source="audio",
                        message=f"Не удалось открыть микрофон: {exc}",
                        recoverable=True,
                    )
                )
                return False

            self._stream = stream
            self._device = resolution.device
            self._start_worker()

        self._bus.publish(
            AudioDeviceChanged(device_name=resolution.device.name, active=True)
        )
        logger.info("Микрофон открыт: %s", resolution.device.name)
        return True

    def stop(self, reason: str = "") -> None:
        """Закрывает поток. После этого системный индикатор микрофона гаснет."""
        with self._lock:
            stream = self._stream
            device = self._device
            self._stream = None
            self._device = None
            self._recording = False

        if stream is None:
            return

        try:
            stream.stop()  # type: ignore[attr-defined]
            stream.close()  # type: ignore[attr-defined]
        except Exception:
            logger.exception("Ошибка при закрытии потока захвата")

        self._stop_worker()
        self._meter.reset()
        self._ring.clear()

        name = device.name if device else ""
        self._bus.publish(AudioDeviceChanged(device_name=name, active=False, reason=reason))
        self._bus.publish(AudioLevelChanged(rms=0.0, peak=0.0))
        logger.info("Микрофон закрыт%s", f": {reason}" if reason else "")

    def restart(self, device_id: int | None = None, device_name: str = "") -> bool:
        """Переоткрывает поток — например, после смены устройства в настройках."""
        self.stop(reason="смена устройства")
        return self.start(device_id=device_id, device_name=device_name)

    # ------------------------------------------------------------------ #
    # Запись основной речи
    # ------------------------------------------------------------------ #

    def begin_recording(
        self,
        max_seconds: float,
        include_pre_roll: bool = True,
    ) -> None:
        """Начинает накопление речи.

        ``max_seconds`` — защитный лимит: он действует всегда, даже когда
        остановка по тишине выключена.
        """
        with self._lock:
            self._recorded = []
            self._recorded_samples = 0
            self._record_truncated = False
            self._dropped_blocks = 0
            self._record_limit_samples = max(
                self._block_size, int(max_seconds * self._sample_rate)
            )
            if include_pre_roll:
                pre_roll = self._ring.read_all()
                if pre_roll.size:
                    self._recorded.append(pre_roll)
                    self._recorded_samples = pre_roll.size
            self._recording = True

    def end_recording(self) -> RecordingResult:
        """Останавливает накопление и отдаёт собранное аудио."""
        with self._lock:
            self._recording = False
            chunks = self._recorded
            truncated = self._record_truncated
            dropped = self._dropped_blocks
            self._recorded = []
            self._recorded_samples = 0

        audio = (
            np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
        )
        return RecordingResult(
            audio=audio,
            sample_rate=self._sample_rate,
            duration_seconds=audio.size / self._sample_rate,
            truncated=truncated,
            dropped_blocks=dropped,
        )

    def cancel_recording(self) -> None:
        with self._lock:
            self._recording = False
            self._recorded = []
            self._recorded_samples = 0

    @property
    def recording_seconds(self) -> float:
        with self._lock:
            return self._recorded_samples / self._sample_rate

    @property
    def recording_limit_reached(self) -> bool:
        with self._lock:
            return self._record_truncated

    # ------------------------------------------------------------------ #
    # Внутреннее
    # ------------------------------------------------------------------ #

    def _audio_callback(self, indata, frames, time_info, status) -> None:  # type: ignore[no-untyped-def]
        """Вызывается в потоке PortAudio. Должен быть максимально коротким."""
        if status:
            logger.debug("Состояние потока захвата: %s", status)

        block = np.asarray(indata, dtype=np.float32).reshape(-1).copy()
        if self._gain != 1.0:
            block *= self._gain

        self._ring.write(block)
        self._meter.update(block)

        try:
            self._queue.put_nowait(block)
        except queue.Full:
            with self._lock:
                self._dropped_blocks += 1

    def _start_worker(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._worker_stop.clear()
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="voiceflow-audio",
            daemon=True,
        )
        self._worker.start()

    def _stop_worker(self) -> None:
        worker = self._worker
        if worker is None:
            return
        self._worker_stop.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        worker.join(timeout=2.0)
        self._worker = None
        self._drain_queue()

    def _drain_queue(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return

    def _worker_loop(self) -> None:
        # Пониженный приоритет: фоновое прослушивание не должно мешать работе.
        _lower_thread_priority()

        while not self._worker_stop.is_set():
            try:
                block = self._queue.get(timeout=0.2)
            except queue.Empty:
                self._publish_level()
                continue
            if block is None:
                break

            self._append_to_recording(block)
            self._feed_consumers(block)
            self._publish_level()

    def _append_to_recording(self, block: np.ndarray) -> None:
        with self._lock:
            if not self._recording:
                return
            if self._recorded_samples >= self._record_limit_samples:
                if not self._record_truncated:
                    self._record_truncated = True
                    logger.info("Достигнут защитный лимит длительности записи")
                return
            remaining = self._record_limit_samples - self._recorded_samples
            piece = block if block.size <= remaining else block[:remaining]
            self._recorded.append(piece)
            self._recorded_samples += piece.size
            if piece.size < block.size:
                self._record_truncated = True

    def _feed_consumers(self, block: np.ndarray) -> None:
        with self._consumers_lock:
            consumers = list(self._consumers)
        for consumer in consumers:
            try:
                consumer(block)
            except Exception:
                logger.exception("Потребитель аудио завершился ошибкой")

    def _publish_level(self) -> None:
        now_ms = _monotonic_ms()
        if now_ms - self._last_level_publish_ms < LEVEL_PUBLISH_INTERVAL_MS:
            return
        self._last_level_publish_ms = now_ms
        reading = self._meter.current
        self._bus.publish(AudioLevelChanged(rms=reading.rms, peak=reading.peak))


def _monotonic_ms() -> float:
    import time

    return time.monotonic() * 1000.0


def _lower_thread_priority() -> None:
    """Понижает приоритет рабочего потока там, где это поддерживается."""
    try:
        import os

        if hasattr(os, "nice"):
            os.nice(5)
    except OSError:
        logger.debug("Не удалось понизить приоритет потока обработки аудио")
