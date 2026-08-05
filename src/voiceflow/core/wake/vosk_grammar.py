"""Детектор команды на Vosk small-ru с ограниченной грамматикой.

Проверенный запасной путь: модель небольшая, грамматика задаётся текстом.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np

from voiceflow import paths
from voiceflow.core.wake.base import DetectorInfo, WakeHit, WakeWordDetector
from voiceflow.core.wake.matcher import normalize_phrase

logger = logging.getLogger(__name__)

MODEL_DIRNAME = "vosk-model-small-ru"


class VoskGrammarDetector(WakeWordDetector):
    engine = "vosk"

    def __init__(self, model_dir: Path | None = None) -> None:
        self._model_dir = model_dir or (paths.models_dir() / "wake" / MODEL_DIRNAME)
        # У vosk нет типовых заглушек, поэтому объекты движка остаются Any.
        self._model: Any = None
        self._recognizer: Any = None
        self._phrases: list[str] = []

    def info(self) -> DetectorInfo:
        ready = self.is_available() and self._model_dir.is_dir()
        return DetectorInfo(
            engine=self.engine,
            title="Vosk small-ru",
            ready=ready,
            notes="" if ready else "модель не загружена",
        )

    def is_available(self) -> bool:
        try:
            import vosk  # noqa: F401

            return True
        except ImportError:
            return False

    def set_phrases(self, phrases: list[str]) -> None:
        # Грамматика Vosk — список целых высказываний-альтернатив.
        # Если разрезать фразу на слова, распознаватель вернёт «слушай» или
        # «сюда» по отдельности, и сравнение с «слушай сюда» никогда не сойдётся.
        normalized: list[str] = []
        seen: set[str] = set()
        for phrase in phrases:
            value = normalize_phrase(phrase)
            if not value or value in seen:
                continue
            seen.add(value)
            normalized.append(value)
        self._phrases = normalized
        self._rebuild(normalized)

    def _ensure_model(self) -> object:
        if self._model is not None:
            return self._model
        if not self.is_available():
            raise RuntimeError("Не установлен пакет vosk. Выполните: uv sync --extra wake-vosk")
        if not self._model_dir.is_dir():
            raise RuntimeError(
                f"Модель Vosk не найдена: {self._model_dir}. Загрузите её в мастере моделей."
            )
        from vosk import Model

        self._model = Model(str(self._model_dir))
        return self._model

    def _rebuild(self, phrases: list[str]) -> None:
        self._recognizer = None
        if not phrases:
            return
        try:
            model = self._ensure_model()
        except Exception as exc:
            logger.warning("Vosk недоступен: %s", exc)
            return
        from vosk import KaldiRecognizer

        grammar = json.dumps([*phrases, "[unk]"], ensure_ascii=False)
        self._recognizer = KaldiRecognizer(model, 16_000, grammar)

    def process(self, audio: np.ndarray, sample_rate: int) -> WakeHit | None:
        if self._recognizer is None:
            return None
        data = np.asarray(audio, dtype=np.float32).reshape(-1)
        if sample_rate != 16_000:
            # Упрощённый ресемплинг: детектор всегда кормится 16 кГц.
            ratio = sample_rate / 16_000
            indices = (np.arange(0, len(data), ratio)).astype(np.int64)
            data = data[indices[indices < len(data)]]
        pcm = np.clip(data * 32767.0, -32768, 32767).astype(np.int16).tobytes()
        recognizer = self._recognizer
        if recognizer.AcceptWaveform(pcm):
            payload = json.loads(recognizer.Result())
        else:
            payload = json.loads(recognizer.FinalResult())
            # После FinalResult распознаватель нужно пересоздать для следующего сегмента.
            self.set_phrases(self._phrases)

        text = normalize_phrase(str(payload.get("text", "")))
        if not text or text == "unk":
            return None
        return WakeHit(text=text, score=1.0, engine=self.engine)

    def reset(self) -> None:
        if self._phrases:
            self.set_phrases(self._phrases)

    def close(self) -> None:
        self._recognizer = None
        self._model = None
