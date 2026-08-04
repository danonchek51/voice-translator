"""Распознавание русской речи моделью GigaAM-v3 через onnxruntime.

Почему именно она основная для русского: при 240 млн параметров средний WER
на русских наборах примерно 8-9 % против 25 % у Whisper-large-v3, лицензия
MIT, а на процессоре она работает более чем в двадцать раз быстрее реального
времени — это единственный вариант, дающий приемлемый отклик на слабой
машине без видеокарты. Варианты ``e2e`` сразу возвращают текст с пунктуацией
и нормализованными числами.

Ограничение: модель только русская, латиница будет записана кириллицей.
Для смешанной русско-английской речи конвейер выбирает Whisper.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from voiceflow.core.asr.base import EngineInfo, ModelNotReadyError, Transcriber
from voiceflow.core.modelstore import repo_has_files

logger = logging.getLogger(__name__)

#: Варианты модели по пресетам качества.
#: CTC быстрее, RNN-T точнее примерно на 0.8 процентного пункта WER.
MODEL_BY_PRESET: dict[str, str] = {
    "light": "gigaam-v3-e2e-ctc",
    "standard": "gigaam-v3-e2e-rnnt",
    "quality": "gigaam-v3-e2e-rnnt",
}

#: Квантизация по устройству: на процессоре выгодно int8, на видеокарте fp16.
QUANTIZATION_BY_DEVICE: dict[str, str | None] = {
    "cpu": "int8",
    "cuda": None,
}

#: Репозитории моделей. Держим у себя, а не читаем из внутренностей onnx-asr:
#: их структура меняется между версиями, а список нужен ещё и вкладке «Модели».
MODEL_REPOS: dict[str, str] = {
    "gigaam-v3-e2e-ctc": "istupakov/gigaam-v3-onnx",
    "gigaam-v3-e2e-rnnt": "istupakov/gigaam-v3-onnx",
    "gigaam-v3-ctc": "istupakov/gigaam-v3-onnx",
    "gigaam-v3-rnnt": "istupakov/gigaam-v3-onnx",
}

#: Начало имён файлов весов внутри репозитория: один репозиторий содержит
#: несколько вариантов модели, и наличие одного не означает наличие другого.
MODEL_FILE_PREFIX: dict[str, str] = {
    "gigaam-v3-e2e-ctc": "v3_e2e_ctc",
    "gigaam-v3-e2e-rnnt": "v3_e2e_rnnt",
    "gigaam-v3-ctc": "v3_ctc",
    "gigaam-v3-rnnt": "v3_rnnt",
}


class GigaAmTranscriber(Transcriber):
    """Движок GigaAM поверх onnx-asr."""

    engine = "gigaam"

    def __init__(self, model_id: str = "gigaam-v3-e2e-rnnt", device: str = "cpu") -> None:
        super().__init__(model_id=model_id, device=device)

    @classmethod
    def for_preset(cls, preset: str, device: str = "cpu") -> GigaAmTranscriber:
        return cls(model_id=MODEL_BY_PRESET.get(preset, MODEL_BY_PRESET["standard"]), device=device)

    def info(self) -> EngineInfo:
        return EngineInfo(
            engine=self.engine,
            model_id=self.model_id,
            title="GigaAM-v3 (русский)",
            languages=("ru",),
            device=self.device,
            notes="Только русский язык, латиница записывается кириллицей",
            extras=("asr",),
        )

    def is_backend_available(self) -> bool:
        try:
            import onnx_asr  # noqa: F401
        except ImportError:
            return False
        return True

    def is_model_ready(self) -> bool:
        """Проверяет наличие файлов весов на диске, не загружая модель."""
        if not self.is_backend_available():
            return False

        repo = MODEL_REPOS.get(self.model_id)
        prefix = MODEL_FILE_PREFIX.get(self.model_id)
        if repo is None or prefix is None:
            logger.debug("Для модели %s не описан репозиторий", self.model_id)
            return False

        # В одном репозитории лежат все варианты модели, поэтому проверяем
        # файлы именно своего: и веса, и словарь.
        return repo_has_files(repo, (f"{prefix}*.onnx", f"{prefix}_vocab.txt"))

    def _providers(self) -> list[str]:
        if self.device == "cuda":
            return ["CUDAExecutionProvider", "CPUExecutionProvider"]
        return ["CPUExecutionProvider"]

    def _load_model(self) -> object:
        import onnx_asr

        try:
            return onnx_asr.load_model(
                self.model_id,
                quantization=QUANTIZATION_BY_DEVICE.get(self.device),
                providers=self._providers(),
            )
        except Exception as exc:
            raise ModelNotReadyError(
                f"Модель {self.model_id} не загружена. "
                "Откройте настройки, вкладка «Модели», и скачайте её."
            ) from exc

    def _transcribe(
        self, audio: np.ndarray, sample_rate: int, language: str | None
    ) -> tuple[str, str]:
        model: Any = self._model
        # GigaAM одноязычная: параметр языка ей передавать нечего.
        text = model.recognize(audio, sample_rate=sample_rate)
        if isinstance(text, list):
            text = " ".join(str(part) for part in text)
        return str(text), "ru"
