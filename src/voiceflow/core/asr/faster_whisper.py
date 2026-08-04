"""Многоязычное распознавание через faster-whisper.

Нужен там, где GigaAM не подходит: автоопределение языка и смешанная
русско-английская речь. Whisper корректно пишет «Cursor», «Python»,
``useEffect``, тогда как русская модель запишет их кириллицей.

Цена: на процессоре Whisper работает примерно в реальном времени, то есть
на слабой машине отклик будет заметным. Для CUDA-режима нужны библиотеки
CUDA 12 и cuDNN 9 — их отсутствие даёт невнятную ошибку загрузки, поэтому
она перехватывается и превращается в понятное сообщение с откатом на
процессор.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from voiceflow import paths
from voiceflow.core.asr.base import EngineInfo, ModelNotReadyError, Transcriber

logger = logging.getLogger(__name__)

MODEL_BY_PRESET: dict[str, str] = {
    "light": "small",
    "standard": "large-v3-turbo",
    "quality": "large-v3",
}

COMPUTE_TYPE_BY_DEVICE: dict[str, str] = {
    "cpu": "int8",
    "cuda": "int8_float16",
}

#: Наводит распознавание на терминологию, которая иначе превращается в кашу.
DEFAULT_PROMPT = "Разговор о программировании: Python, Cursor, GitHub, API, Docker."


class FasterWhisperTranscriber(Transcriber):
    """Движок Whisper поверх CTranslate2."""

    engine = "whisper"

    def __init__(self, model_id: str = "large-v3-turbo", device: str = "cpu") -> None:
        super().__init__(model_id=model_id, device=device)
        self._fell_back_to_cpu = False

    @classmethod
    def for_preset(cls, preset: str, device: str = "cpu") -> FasterWhisperTranscriber:
        return cls(
            model_id=MODEL_BY_PRESET.get(preset, MODEL_BY_PRESET["standard"]),
            device=device,
        )

    def info(self) -> EngineInfo:
        notes = "99 языков, автоопределение языка"
        if self._fell_back_to_cpu:
            notes += ". CUDA недоступна, работает на процессоре"
        return EngineInfo(
            engine=self.engine,
            model_id=self.model_id,
            title=f"Whisper {self.model_id}",
            languages=("ru", "en", "auto"),
            device="cpu" if self._fell_back_to_cpu else self.device,
            notes=notes,
            extras=("whisper",),
        )

    def is_backend_available(self) -> bool:
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            return False
        return True

    def is_model_ready(self) -> bool:
        """Наличие весов именно нужного размера, а не какой-нибудь модели."""
        if not self.is_backend_available():
            return False
        root = paths.whisper_models_dir()
        if not root.exists():
            return False
        # faster-whisper кладёт веса в models--Systran--faster-whisper-<размер>.
        pattern = f"*faster-whisper-{self.model_id}*"
        return any(
            candidate.is_file()
            for directory in root.glob(pattern)
            for candidate in directory.rglob("model.bin")
        )

    def _load_model(self) -> object:
        from faster_whisper import WhisperModel

        download_root = str(paths.whisper_models_dir())
        paths.whisper_models_dir().mkdir(parents=True, exist_ok=True)

        try:
            return WhisperModel(
                self.model_id,
                device=self.device,
                compute_type=COMPUTE_TYPE_BY_DEVICE.get(self.device, "int8"),
                download_root=download_root,
                local_files_only=True,
            )
        except Exception as exc:
            if self.device == "cuda":
                logger.warning(
                    "Не удалось запустить Whisper на видеокарте (%s). "
                    "Обычно не хватает библиотек CUDA 12 и cuDNN 9. Пробую процессор.",
                    exc,
                )
                return self._load_on_cpu(download_root, exc)
            raise ModelNotReadyError(
                f"Модель Whisper «{self.model_id}» не загружена. "
                "Откройте настройки, вкладка «Модели», и скачайте её."
            ) from exc

    def _load_on_cpu(self, download_root: str, original: Exception) -> object:
        from faster_whisper import WhisperModel

        try:
            model = WhisperModel(
                self.model_id,
                device="cpu",
                compute_type=COMPUTE_TYPE_BY_DEVICE["cpu"],
                download_root=download_root,
                local_files_only=True,
            )
        except Exception as exc:
            raise ModelNotReadyError(
                f"Модель Whisper «{self.model_id}» недоступна ни на видеокарте, ни на "
                "процессоре. Проверьте вкладку «Модели»."
            ) from exc
        self._fell_back_to_cpu = True
        return model

    def _transcribe(
        self, audio: np.ndarray, sample_rate: int, language: str | None
    ) -> tuple[str, str]:
        model: Any = self._model
        if sample_rate != 16_000:
            raise ValueError("Whisper ожидает частоту дискретизации 16 кГц")

        segments, info = model.transcribe(
            audio,
            language=language,
            beam_size=5,
            # Внутренний VAD Whisper режет речь и добавляет 3-4 процентных
            # пункта к ошибке. Тишину отсекает наш собственный конвейер.
            vad_filter=False,
            condition_on_previous_text=False,
            initial_prompt=DEFAULT_PROMPT,
        )
        text = " ".join(segment.text.strip() for segment in segments)
        detected = getattr(info, "language", "") or language or ""
        return text, detected
