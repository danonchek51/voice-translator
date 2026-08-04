"""Интерфейс детектора голосовой команды.

Реализации прячутся за одним классом: конвейер и сервис активации не зависят
от того, выбран ли Vosk или sherpa-onnx.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WakeHit:
    """Срабатывание детектора."""

    text: str
    score: float
    engine: str


@dataclass(frozen=True, slots=True)
class DetectorInfo:
    engine: str
    title: str
    ready: bool
    notes: str = ""


class WakeWordDetector(ABC):
    """Мини-ASR с ограниченным словарём."""

    engine: str = "base"

    @abstractmethod
    def info(self) -> DetectorInfo: ...

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def set_phrases(self, phrases: list[str]) -> None:
        """Обновляет список ожидаемых фраз (старт и стоп)."""

    @abstractmethod
    def process(self, audio: np.ndarray, sample_rate: int) -> WakeHit | None:
        """Пытается распознать команду в коротком сегменте речи."""

    def reset(self) -> None:  # noqa: B027 — хук по желанию реализации
        """Сбрасывает внутреннее состояние потока. Не всем движкам нужно."""

    def close(self) -> None:  # noqa: B027 — хук по желанию реализации
        """Освобождает ресурсы. Заглушке освобождать нечего."""
