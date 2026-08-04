"""Единственный канал событий приложения.

Ядро публикует события, интерфейс на них подписывается. Обратной зависимости
нет: ``core`` ничего не знает про Qt. Параллельные каналы событий заводить
нельзя — расширяем этот.

Доставка синхронная, в потоке публикующего. Обработчики обязаны быть быстрыми
и не блокировать: слой интерфейса сам перекладывает событие в поток Qt.
Исключение в обработчике не мешает остальным подписчикам.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar

from voiceflow.core.state import AppState

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Event:
    """Базовый тип события."""


@dataclass(frozen=True, slots=True)
class StateChanged(Event):
    """Машина состояний перешла в новое состояние."""

    old: AppState
    new: AppState
    detail: str = ""


@dataclass(frozen=True, slots=True)
class AudioLevelChanged(Event):
    """Текущий уровень микрофона.

    Значения нормированы в диапазон 0..1. Само аудио наружу не уходит.
    """

    rms: float
    peak: float


@dataclass(frozen=True, slots=True)
class AudioDeviceChanged(Event):
    """Устройство захвата открыто, закрыто или потеряно."""

    device_name: str
    active: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ErrorOccurred(Event):
    """Сбой подсистемы.

    ``recoverable`` означает, что приложение продолжит работу в урезанном виде.
    """

    source: str
    message: str
    recoverable: bool = True


@dataclass(frozen=True, slots=True)
class NoticeIssued(Event):
    """Информационное сообщение для пользователя, не являющееся ошибкой."""

    source: str
    message: str


@dataclass(frozen=True, slots=True)
class SettingsChanged(Event):
    """Настройки сохранены. ``sections`` — какие разделы затронуты."""

    sections: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class RecordingStarted(Event):
    """Началась запись основной речи."""

    source: str


@dataclass(frozen=True, slots=True)
class RecordingFinished(Event):
    """Запись остановлена.

    ``truncated`` означает, что сработал защитный лимит длительности.
    """

    duration_seconds: float
    truncated: bool = False
    cancelled: bool = False


@dataclass(frozen=True, slots=True)
class TextProcessed(Event):
    """Текст прошёл цепочку включённых шагов обработки."""

    raw: str
    cleaned: str
    final: str
    #: Шаги, которые применились: ``clean``, ``translate``, ``prompt``.
    #: Пустой набор означает дословный текст.
    steps: tuple[str, ...] = ()
    used_llm: bool = False
    #: Почему языковая модель не применялась. Штатная деградация, не ошибка.
    fallback_reason: str = ""


@dataclass(frozen=True, slots=True)
class ResultDelivered(Event):
    """Итоговый текст доставлен: скопирован и, возможно, вставлен."""

    text: str
    copied: bool
    pasted: bool
    message: str
    target: str = ""


@dataclass(frozen=True, slots=True)
class TranscriptReady(Event):
    """Речь распознана.

    Текст передаётся только в памяти: в лог он не попадает, пока пользователь
    не включит отладку.
    """

    text: str
    language: str
    engine: str
    model_id: str
    audio_seconds: float
    elapsed_seconds: float
    empty_reason: str = ""


@dataclass(frozen=True, slots=True)
class WakeDebug(Event):
    """Отладка детектора команды: распознанное и score в реальном времени.

    Текст не пишется в историю и в обычный лог — только в режим отладки.
    """

    text: str
    score: float
    matched: bool
    engine: str


E = TypeVar("E", bound=Event)
Unsubscribe = Callable[[], None]


class EventBus:
    """Потокобезопасная шина событий с подпиской по типу события."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._handlers: dict[type[Event], list[Callable[[Event], None]]] = {}

    def subscribe(self, event_type: type[E], handler: Callable[[E], None]) -> Unsubscribe:
        """Подписывает обработчик и возвращает функцию отписки."""
        with self._lock:
            bucket = self._handlers.setdefault(event_type, [])
            bucket.append(handler)  # type: ignore[arg-type]

        def unsubscribe() -> None:
            with self._lock:
                current = self._handlers.get(event_type)
                if current and handler in current:  # type: ignore[operator]
                    current.remove(handler)  # type: ignore[arg-type]

        return unsubscribe

    def publish(self, event: Event) -> None:
        """Доставляет событие подписчикам его типа и всех базовых типов."""
        with self._lock:
            targets: list[Callable[[Event], None]] = []
            for event_type in type(event).__mro__:
                if not isinstance(event_type, type) or not issubclass(event_type, Event):
                    continue
                targets.extend(self._handlers.get(event_type, ()))

        for handler in targets:
            try:
                handler(event)
            except Exception:
                logger.exception("Обработчик события %s завершился ошибкой", type(event).__name__)

    def clear(self) -> None:
        """Снимает все подписки. Нужно для тестов и для корректного завершения."""
        with self._lock:
            self._handlers.clear()
