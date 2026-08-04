"""Подставные реализации подсистем для тестов.

Позволяют проверять конвейер целиком без моделей, микрофона и сети.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from voiceflow.core.asr.base import EngineInfo, Transcriber, TranscriberError
from voiceflow.core.audio.capture import RecordingResult
from voiceflow.platform.base import WindowInfo


class FakeTranscriber(Transcriber):
    """Движок распознавания, возвращающий заранее заданный текст."""

    engine = "fake"

    def __init__(
        self,
        text: str = "тестовый текст",
        backend_available: bool = True,
        model_ready: bool = True,
        language: str = "ru",
        raises: Exception | None = None,
    ) -> None:
        super().__init__(model_id="fake-model", device="cpu")
        self.text = text
        self.language = language
        self.backend_available = backend_available
        self.model_ready = model_ready
        self.raises = raises
        self.load_count = 0
        self.calls: list[tuple[int, str | None]] = []

    def info(self) -> EngineInfo:
        return EngineInfo(
            engine=self.engine,
            model_id=self.model_id,
            title="Подставной движок",
            languages=("ru",),
            device=self.device,
        )

    def is_backend_available(self) -> bool:
        return self.backend_available

    def is_model_ready(self) -> bool:
        return self.model_ready

    def _load_model(self) -> object:
        self.load_count += 1
        return object()

    def _transcribe(
        self, audio: np.ndarray, sample_rate: int, language: str | None
    ) -> tuple[str, str]:
        self.calls.append((audio.size, language))
        if self.raises is not None:
            raise self.raises
        return self.text, self.language


class FakeCapture:
    """Захват аудио без микрофона: запись подсовывается вручную."""

    def __init__(self, sample_rate: int = 16_000) -> None:
        self.sample_rate = sample_rate
        self.is_running = True
        self.is_recording = False
        self.recording_limit_reached = False
        self.recording_seconds = 0.0
        self.next_audio = np.ones(16_000, dtype=np.float32)
        self.truncated = False
        self.begin_calls: list[float] = []
        self.cancelled = False
        self._consumers: list[Callable[[np.ndarray], None]] = []

    def add_consumer(self, consumer: Callable[[np.ndarray], None]) -> Callable[[], None]:
        self._consumers.append(consumer)

        def remove() -> None:
            if consumer in self._consumers:
                self._consumers.remove(consumer)

        return remove

    def feed(self, block: np.ndarray) -> None:
        for consumer in list(self._consumers):
            consumer(block)

    @property
    def consumer_count(self) -> int:
        return len(self._consumers)

    def begin_recording(self, max_seconds: float, include_pre_roll: bool = True) -> None:
        self.begin_calls.append(max_seconds)
        self.is_recording = True
        self.cancelled = False

    def end_recording(self) -> RecordingResult:
        self.is_recording = False
        audio = self.next_audio
        return RecordingResult(
            audio=audio,
            sample_rate=self.sample_rate,
            duration_seconds=audio.size / self.sample_rate,
            truncated=self.truncated,
        )

    def cancel_recording(self) -> None:
        self.is_recording = False
        self.cancelled = True


class FakeClipboard:
    """Буфер обмена в памяти, умеющий изображать занятость."""

    def __init__(self, text: str | None = None) -> None:
        self.text = text
        self.fail_on_set = False
        self.set_calls: list[str] = []

    def set_text(self, text: str) -> bool:
        self.set_calls.append(text)
        if self.fail_on_set:
            return False
        self.text = text
        return True

    def get_text(self) -> str | None:
        return self.text


class FakeWindows:
    """Активное окно без Windows."""

    def __init__(self, target: WindowInfo | None = None) -> None:
        self.target = target or WindowInfo(handle=1, title="Блокнот", process_name="notepad.exe")
        self.window_exists = True
        self.window_active = True
        self.can_activate = True
        self.activate_calls = 0

    def current(self) -> WindowInfo | None:
        return self.target

    def exists(self, handle: int) -> bool:
        return self.window_exists

    def is_active(self, handle: int) -> bool:
        return self.window_active

    def activate(self, handle: int) -> bool:
        self.activate_calls += 1
        if self.can_activate:
            self.window_active = True
        return self.can_activate


class FakePaster:
    """Отправка нажатий без системы ввода."""

    def __init__(self) -> None:
        self.succeed = True
        self.paste_calls: list[str] = []
        self.typed: list[str] = []

    def paste(self, method: str) -> bool:
        self.paste_calls.append(method)
        return self.succeed

    def type_text(self, text: str) -> bool:
        self.typed.append(text)
        return self.succeed


class FakeRegistry:
    """Реестр движков, всегда отдающий один и тот же подставной движок."""

    def __init__(self, transcriber: Transcriber | None = None, note: str = "") -> None:
        self.transcriber = transcriber or FakeTranscriber()
        self.note = note
        self.error: TranscriberError | None = None
        self.unload_calls = 0

    def resolve(self):  # type: ignore[no-untyped-def]
        from voiceflow.core.asr.registry import EngineSelection, ResolvedTranscriber

        if self.error is not None:
            raise self.error
        return ResolvedTranscriber(
            transcriber=self.transcriber,
            selection=EngineSelection(self.transcriber.engine, "тест"),
            note=self.note,
        )

    def unload_all(self) -> None:
        self.unload_calls += 1
