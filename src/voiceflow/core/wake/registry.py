"""Выбор реализации детектора голосовой команды."""

from __future__ import annotations

import logging

import numpy as np

from voiceflow.core.wake.base import DetectorInfo, WakeHit, WakeWordDetector
from voiceflow.core.wake.sherpa_kws import SherpaKwsDetector
from voiceflow.core.wake.vosk_grammar import VoskGrammarDetector

logger = logging.getLogger(__name__)


class NullWakeDetector(WakeWordDetector):
    """Заглушка: голосовая активация недоступна."""

    engine = "null"

    def info(self) -> DetectorInfo:
        return DetectorInfo(
            engine=self.engine,
            title="Голосовая активация недоступна",
            ready=False,
            notes="установите Vosk или sherpa-onnx и загрузите модель",
        )

    def is_available(self) -> bool:
        return False

    def set_phrases(self, phrases: list[str]) -> None:
        return None

    def process(self, audio: np.ndarray, sample_rate: int) -> WakeHit | None:
        return None


def create_wake_detector(preferred: str = "auto") -> WakeWordDetector:
    """Создаёт лучший доступный детектор.

    Порядок по умолчанию: Vosk (проверенный путь), затем sherpa.
    """
    candidates: list[WakeWordDetector] = []
    if preferred in ("auto", "vosk"):
        candidates.append(VoskGrammarDetector())
    if preferred in ("auto", "sherpa"):
        candidates.append(SherpaKwsDetector())
    if preferred == "sherpa" and not any(isinstance(c, SherpaKwsDetector) for c in candidates):
        candidates.insert(0, SherpaKwsDetector())

    for detector in candidates:
        info = detector.info()
        if detector.is_available() and info.ready:
            logger.info("Детектор команды: %s", info.title)
            return detector
        if detector.is_available():
            logger.info(
                "Детектор %s доступен, но модель не готова: %s",
                info.title,
                info.notes,
            )

    # Библиотека есть — вернём её, чтобы мастер моделей знал, что качать.
    for detector in candidates:
        if detector.is_available():
            return detector

    logger.warning("Нет доступного детектора голосовой команды")
    return NullWakeDetector()
