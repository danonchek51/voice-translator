"""Интерфейс распознавания речи.

Все движки прячутся за одним классом, поэтому замена модели не затрагивает
конвейер. Требования к реализации:

* загрузка модели отложенная — приложение стартует за секунду даже без моделей;
* отсутствие модели или библиотеки не роняет приложение, а превращается
  в понятное сообщение;
* модель можно выгрузить, освободив видеопамять под локальную LLM.
"""

from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)

#: Короче этого распознавать нечего: обычно это случайный щелчок.
MIN_AUDIO_SECONDS = 0.25

#: Меньше этого числа потоков распознавание становится заметно медленным.
MIN_INFERENCE_THREADS = 2


def inference_threads() -> int:
    """Сколько потоков отдать распознаванию.

    Берётся половина логических ядер, то есть примерно число физических:
    у соседних потоков одного ядра общие исполнительные блоки, и загрузка
    их всех замедляет саму работу, а заодно отбирает процессор у системы.

    Замер на двенадцати логических ядрах, пятнадцать секунд речи:

    ===============  ==============  =============
    Потоков          Распознавание   Занято ядер
    ===============  ==============  =============
    по умолчанию     2.36 с          5.3
    12               3.72 с          8.5
    6                1.98 с          5.8
    4                2.51 с          3.9
    ===============  ==============  =============
    """
    import os

    total = os.cpu_count() or 4
    return max(MIN_INFERENCE_THREADS, total // 2)


@dataclass(frozen=True, slots=True)
class TranscriptResult:
    """Результат распознавания."""

    text: str
    language: str
    engine: str
    model_id: str
    audio_seconds: float
    elapsed_seconds: float
    #: Причина, по которой текст пуст. Пустая строка означает штатный результат.
    empty_reason: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()

    @property
    def speed_ratio(self) -> float:
        """Во сколько раз распознавание быстрее реального времени."""
        if self.elapsed_seconds <= 0:
            return 0.0
        return self.audio_seconds / self.elapsed_seconds


class TranscriberError(RuntimeError):
    """Общая ошибка распознавания."""


class BackendUnavailableError(TranscriberError):
    """Не установлена библиотека движка."""


class ModelNotReadyError(TranscriberError):
    """Библиотека есть, но файлы модели не загружены."""


@dataclass(slots=True)
class EngineInfo:
    """Описание движка для интерфейса и диагностики."""

    engine: str
    model_id: str
    title: str
    languages: tuple[str, ...]
    device: str = "cpu"
    notes: str = ""
    extras: tuple[str, ...] = field(default_factory=tuple)


class Transcriber(ABC):
    """Базовый класс движка распознавания."""

    engine: str = "base"

    def __init__(self, model_id: str, device: str = "cpu") -> None:
        self._model_id = model_id
        self._device = device
        self._model: object | None = None
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ #
    # Сведения
    # ------------------------------------------------------------------ #

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def device(self) -> str:
        return self._device

    @property
    def is_loaded(self) -> bool:
        with self._lock:
            return self._model is not None

    @abstractmethod
    def info(self) -> EngineInfo:
        """Человекочитаемое описание движка."""

    @abstractmethod
    def is_backend_available(self) -> bool:
        """Установлена ли нужная библиотека."""

    @abstractmethod
    def is_model_ready(self) -> bool:
        """Загружены ли файлы модели на диск."""

    # ------------------------------------------------------------------ #
    # Жизненный цикл модели
    # ------------------------------------------------------------------ #

    def load(self) -> None:
        """Загружает модель в память. Повторный вызов ничего не делает."""
        with self._lock:
            if self._model is not None:
                return
            if not self.is_backend_available():
                raise BackendUnavailableError(
                    f"Не установлена библиотека для движка «{self.engine}». "
                    f"Выполните: uv sync --extra {self.info().extras[0]}"
                    if self.info().extras
                    else f"Не установлена библиотека для движка «{self.engine}»"
                )
            started = time.monotonic()
            self._model = self._load_model()
            logger.info(
                "Модель %s загружена за %.1f с (%s)",
                self._model_id,
                time.monotonic() - started,
                self._device,
            )

    def unload(self) -> None:
        """Выгружает модель, освобождая память и видеопамять."""
        with self._lock:
            if self._model is None:
                return
            self._model = None
        logger.info("Модель %s выгружена", self._model_id)

    @abstractmethod
    def _load_model(self) -> object:
        """Создаёт объект модели. Вызывается под блокировкой."""

    @abstractmethod
    def _transcribe(
        self, audio: np.ndarray, sample_rate: int, language: str | None
    ) -> tuple[str, str]:
        """Распознаёт аудио. Возвращает текст и определённый язык."""

    # ------------------------------------------------------------------ #
    # Распознавание
    # ------------------------------------------------------------------ #

    def transcribe(
        self,
        audio: np.ndarray,
        sample_rate: int,
        language: str | None = None,
    ) -> TranscriptResult:
        """Распознаёт запись. Слишком короткое аудио отсекается без модели."""
        data = np.asarray(audio, dtype=np.float32).reshape(-1)
        audio_seconds = data.size / sample_rate if sample_rate else 0.0

        if audio_seconds < MIN_AUDIO_SECONDS:
            return TranscriptResult(
                text="",
                language=language or "",
                engine=self.engine,
                model_id=self._model_id,
                audio_seconds=audio_seconds,
                elapsed_seconds=0.0,
                empty_reason="запись слишком короткая",
            )

        self.load()
        started = time.monotonic()
        with self._lock:
            text, detected = self._transcribe(data, sample_rate, language)
        elapsed = time.monotonic() - started

        cleaned = text.strip()
        return TranscriptResult(
            text=cleaned,
            language=detected or language or "",
            engine=self.engine,
            model_id=self._model_id,
            audio_seconds=audio_seconds,
            elapsed_seconds=elapsed,
            empty_reason="" if cleaned else "речь не распознана",
        )
