"""Выбор движка распознавания.

Правило выбора одно и живёт здесь, чтобы конвейеру не пришлось знать про
особенности моделей. Добавление нового движка — это новый класс и одна
строка в :data:`ENGINE_FACTORIES`.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass

from voiceflow.core.asr.base import EngineInfo, Transcriber, TranscriberError
from voiceflow.core.asr.faster_whisper import FasterWhisperTranscriber
from voiceflow.core.asr.gigaam_onnx import GigaAmTranscriber
from voiceflow.core.settings.schema import RecognitionSettings

logger = logging.getLogger(__name__)

EngineFactory = Callable[[str, str], Transcriber]

ENGINE_FACTORIES: dict[str, EngineFactory] = {
    "gigaam": lambda preset, device: GigaAmTranscriber.for_preset(preset, device),
    "whisper": lambda preset, device: FasterWhisperTranscriber.for_preset(preset, device),
}

#: Лёгкий пресет предназначен для машин без видеокарты.
CPU_ONLY_PRESETS = frozenset({"light"})


@dataclass(frozen=True, slots=True)
class EngineSelection:
    engine: str
    reason: str


def select_engine(recognition: RecognitionSettings) -> EngineSelection:
    """Решает, какой движок нужен при текущих настройках."""
    if recognition.engine in ENGINE_FACTORIES:
        return EngineSelection(recognition.engine, "выбран вручную в настройках")

    if recognition.language_mode == "auto":
        return EngineSelection("whisper", "включено автоопределение языка")

    if recognition.primary_language == "ru":
        return EngineSelection("gigaam", "основной язык русский")

    return EngineSelection("whisper", f"основной язык {recognition.primary_language}")


def detect_device(preset: str) -> str:
    """Определяет, доступна ли видеокарта для onnxruntime."""
    if preset in CPU_ONLY_PRESETS:
        return "cpu"
    try:
        import onnxruntime

        if "CUDAExecutionProvider" in onnxruntime.get_available_providers():
            return "cuda"
    except ImportError:
        pass
    return "cpu"


@dataclass(frozen=True, slots=True)
class ResolvedTranscriber:
    transcriber: Transcriber
    selection: EngineSelection
    #: Пояснение, если пришлось взять не тот движок, который выбирали.
    note: str = ""


class TranscriberRegistry:
    """Создаёт и кэширует движки, переживая смену настроек."""

    def __init__(self, recognition_provider: Callable[[], RecognitionSettings]) -> None:
        self._recognition_provider = recognition_provider
        self._instances: dict[tuple[str, str, str], Transcriber] = {}
        self._lock = threading.RLock()

    def resolve(self) -> ResolvedTranscriber:
        """Возвращает готовый движок или падает с понятным сообщением."""
        recognition = self._recognition_provider()
        preset = recognition.preset
        device = detect_device(preset)
        selection = select_engine(recognition)

        primary = self._get(selection.engine, preset, device)
        if self._is_usable(primary):
            return ResolvedTranscriber(transcriber=primary, selection=selection)

        for name in ENGINE_FACTORIES:
            if name == selection.engine:
                continue
            candidate = self._get(name, preset, device)
            if self._is_usable(candidate):
                note = (
                    f"Движок «{selection.engine}» недоступен "
                    f"({self._unavailable_reason(primary)}), использую «{name}»"
                )
                logger.warning(note)
                return ResolvedTranscriber(
                    transcriber=candidate, selection=selection, note=note
                )

        raise TranscriberError(
            "Ни один движок распознавания не готов. Откройте настройки, "
            "вкладка «Модели», и загрузите модель."
        )

    def _get(self, engine: str, preset: str, device: str) -> Transcriber:
        key = (engine, preset, device)
        with self._lock:
            existing = self._instances.get(key)
            if existing is not None:
                return existing
            factory = ENGINE_FACTORIES[engine]
            created = factory(preset, device)
            self._instances[key] = created
            return created

    @staticmethod
    def _is_usable(transcriber: Transcriber) -> bool:
        return transcriber.is_backend_available() and transcriber.is_model_ready()

    @staticmethod
    def _unavailable_reason(transcriber: Transcriber) -> str:
        if not transcriber.is_backend_available():
            return "не установлена библиотека"
        return "не загружена модель"

    def describe_all(self) -> list[EngineInfo]:
        """Сводка по всем движкам для вкладок «Модели» и «Диагностика»."""
        recognition = self._recognition_provider()
        device = detect_device(recognition.preset)
        return [
            self._get(name, recognition.preset, device).info() for name in ENGINE_FACTORIES
        ]

    def preload(self) -> threading.Thread | None:
        """Заранее поднимает модель в фоне.

        Первая загрузка занимает пять-семь секунд, и без этого она случалась
        ровно в момент окончания первой записи — человек уже сказал фразу и
        ждёт текст, а вместо этого получает паузу. Приложение только что
        стартовало и всё равно ничем не занято, поэтому платим тогда.

        Возвращает поток — он нужен тестам; ошибки сюда не выходят: модели
        может не быть, и это штатный случай, о котором скажет мастер.
        """

        def work() -> None:
            from voiceflow.platform.base import lower_current_thread_priority

            lower_current_thread_priority()
            try:
                resolved = self.resolve()
                resolved.transcriber.load()
            except TranscriberError as exc:
                logger.info("Предзагрузка распознавания пропущена: %s", exc)
            except Exception:
                logger.exception("Предзагрузка распознавания не удалась")
            else:
                logger.info("Модель распознавания готова заранее")

        thread = threading.Thread(target=work, name="voiceflow-preload", daemon=True)
        thread.start()
        return thread

    def unload_all(self) -> None:
        """Освобождает память и видеопамять — например, перед запуском LLM."""
        with self._lock:
            instances = list(self._instances.values())
        for transcriber in instances:
            transcriber.unload()

    def invalidate(self) -> None:
        """Сбрасывает кэш после смены пресета или движка в настройках."""
        self.unload_all()
        with self._lock:
            self._instances.clear()
