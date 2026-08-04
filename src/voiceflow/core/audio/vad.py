"""Детектор речи на Silero VAD.

Работает как «ворота»: пока речи нет, тяжёлый детектор команды не запускается.
Модель маленькая (около 2 MB) и живёт в каталоге моделей приложения.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np

from voiceflow import paths

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
#: Silero ожидает ровно 512 сэмплов при 16 кГц (32 мс).
WINDOW_SIZE = 512

#: Имя файла модели внутри каталога моделей.
MODEL_FILENAME = "silero_vad.onnx"


class VoiceActivityDetector(ABC):
    """Интерфейс детектора речи."""

    @abstractmethod
    def is_speech(self, block: np.ndarray) -> bool:
        """Есть ли речь в блоке 32 мс."""

    def reset(self) -> None:  # noqa: B027 — хук по желанию реализации
        """Сбрасывает внутреннее состояние. У детектора без памяти делать нечего."""


class EnergyVad(VoiceActivityDetector):
    """Запасной детектор по энергии.

    Используется, пока файл Silero не загружен. Порог подобран под речь
    рядом с микрофоном; для продакшена предпочтителен Silero.
    """

    def __init__(self, threshold: float = 0.015) -> None:
        self._threshold = threshold

    def is_speech(self, block: np.ndarray) -> bool:
        data = np.asarray(block, dtype=np.float32).reshape(-1)
        if data.size == 0:
            return False
        rms = float(np.sqrt(np.mean(np.square(data))))
        return rms >= self._threshold


class SileroVad(VoiceActivityDetector):
    """Silero VAD через onnxruntime."""

    def __init__(self, model_path: Path, threshold: float = 0.5) -> None:
        import onnxruntime as ort

        self._threshold = threshold
        self._session = ort.InferenceSession(
            str(model_path),
            providers=["CPUExecutionProvider"],
        )
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._sr = np.array(SAMPLE_RATE, dtype=np.int64)

    def reset(self) -> None:
        self._state = np.zeros((2, 1, 128), dtype=np.float32)

    def is_speech(self, block: np.ndarray) -> bool:
        data = np.asarray(block, dtype=np.float32).reshape(-1)
        if data.size < WINDOW_SIZE:
            padded = np.zeros(WINDOW_SIZE, dtype=np.float32)
            padded[: data.size] = data
            data = padded
        elif data.size > WINDOW_SIZE:
            data = data[:WINDOW_SIZE]

        ort_inputs = {
            "input": data.reshape(1, -1),
            "state": self._state,
            "sr": self._sr,
        }
        outputs = self._session.run(None, ort_inputs)
        self._state = outputs[1]
        probability = float(outputs[0].reshape(-1)[0])
        return probability >= self._threshold


def default_vad_model_path() -> Path:
    return paths.models_dir() / "vad" / MODEL_FILENAME


def create_vad(threshold: float = 0.5) -> VoiceActivityDetector:
    """Создаёт лучший доступный детектор речи."""
    model_path = default_vad_model_path()
    if model_path.is_file():
        try:
            return SileroVad(model_path, threshold=threshold)
        except Exception:
            logger.exception("Не удалось загрузить Silero VAD, использую энергетический")
    else:
        logger.debug("Silero VAD не найден (%s), использую энергетический", model_path)
    return EnergyVad()
