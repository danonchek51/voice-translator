"""Детектор команды на sherpa-onnx KeywordSpotter.

Открытый словарь: ключевые слова задаются текстом без переобучения.
Итоговый выбор движка — по наличию русской KWS-модели и результатам проб.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from voiceflow import paths
from voiceflow.core.wake.base import DetectorInfo, WakeHit, WakeWordDetector
from voiceflow.core.wake.matcher import normalize_phrase

logger = logging.getLogger(__name__)

MODEL_DIRNAME = "sherpa-kws-ru"


class SherpaKwsDetector(WakeWordDetector):
    engine = "sherpa"

    def __init__(self, model_dir: Path | None = None) -> None:
        self._model_dir = model_dir or (paths.models_dir() / "wake" / MODEL_DIRNAME)
        # У sherpa-onnx нет типовых заглушек, поэтому объекты движка — Any.
        self._spotter: Any = None
        self._stream: Any = None
        self._phrases: list[str] = []
        self._keywords: str = ""

    def info(self) -> DetectorInfo:
        ready = self.is_available() and self._model_dir.is_dir()
        return DetectorInfo(
            engine=self.engine,
            title="sherpa-onnx KeywordSpotter",
            ready=ready,
            notes="" if ready else "модель не загружена",
        )

    def is_available(self) -> bool:
        try:
            import sherpa_onnx  # noqa: F401

            return True
        except ImportError:
            return False

    def set_phrases(self, phrases: list[str]) -> None:
        normalized = [normalize_phrase(p) for p in phrases if normalize_phrase(p)]
        self._phrases = normalized
        # Формат keywords.txt sherpa: слова через пробел, фразы через перевод строки.
        self._keywords = "\n".join(normalized)
        self._rebuild()

    def _rebuild(self) -> None:
        self._spotter = None
        self._stream = None
        if not self._keywords:
            return
        if not self.is_available():
            logger.debug("sherpa-onnx не установлен")
            return
        if not self._model_dir.is_dir():
            logger.debug("Модель sherpa KWS не найдена: %s", self._model_dir)
            return

        try:
            import sherpa_onnx

            encoder = self._find("encoder*.onnx")
            decoder = self._find("decoder*.onnx")
            joiner = self._find("joiner*.onnx")
            tokens = self._find("tokens.txt")
            if not all((encoder, decoder, joiner, tokens)):
                logger.warning("Неполный набор файлов sherpa KWS в %s", self._model_dir)
                return

            keywords_file = self._model_dir / "keywords.txt"
            keywords_file.write_text(self._keywords + "\n", encoding="utf-8")

            config = sherpa_onnx.KeywordSpotterConfig(
                feat_config=sherpa_onnx.FeatureConfig(),
                model_config=sherpa_onnx.OfflineModelConfig(
                    transducer=sherpa_onnx.OfflineTransducerModelConfig(
                        encoder=str(encoder),
                        decoder=str(decoder),
                        joiner=str(joiner),
                    ),
                    tokens=str(tokens),
                ),
                keywords_file=str(keywords_file),
            )
            # Часть сборок использует Online/KeywordSpotter с другим API.
            # Пробуем KeywordSpotter; при несовпадении API остаёмся без движка.
            if hasattr(sherpa_onnx, "KeywordSpotter"):
                self._spotter = sherpa_onnx.KeywordSpotter(config)
                self._stream = self._spotter.create_stream()
            else:
                logger.warning("В установленной sherpa-onnx нет KeywordSpotter")
        except Exception:
            logger.exception("Не удалось инициализировать sherpa-onnx KWS")
            self._spotter = None
            self._stream = None

    def _find(self, pattern: str) -> Path | None:
        matches = sorted(self._model_dir.glob(pattern))
        return matches[0] if matches else None

    def process(self, audio: np.ndarray, sample_rate: int) -> WakeHit | None:
        if self._spotter is None or self._stream is None:
            return None
        data = np.asarray(audio, dtype=np.float32).reshape(-1)
        try:
            self._stream.accept_waveform(sample_rate, data)
            self._spotter.decode_stream(self._stream)
            result = self._spotter.get_result(self._stream)
            text = normalize_phrase(str(getattr(result, "keyword", "") or result))
            if not text:
                return None
            score = float(getattr(result, "json", 1.0) if False else 1.0)
            return WakeHit(text=text, score=score, engine=self.engine)
        except Exception:
            logger.exception("Ошибка sherpa-onnx KWS")
            return None

    def reset(self) -> None:
        if self._spotter is not None and hasattr(self._spotter, "create_stream"):
            self._stream = self._spotter.create_stream()

    def close(self) -> None:
        self._stream = None
        self._spotter = None
