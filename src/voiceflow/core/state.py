"""Машина состояний приложения.

Состояния отражают то, что видит пользователь на плашке. Любой переход идёт
только через :class:`StateMachine`, чтобы плашка, трей и логи всегда описывали
одно и то же.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from enum import Enum

logger = logging.getLogger(__name__)


class AppState(Enum):
    """Состояния конвейера. Значение используется в логах и в настройках."""

    IDLE = "idle"
    LISTENING = "listening"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    PROCESSING = "processing"
    PASTING = "pasting"
    ERROR = "error"
    PAUSED = "paused"


#: Подписи для плашки. Держим рядом с состояниями, чтобы не разошлись.
STATE_LABELS: dict[AppState, str] = {
    AppState.IDLE: "Готово",
    AppState.LISTENING: "Слушаю",
    AppState.RECORDING: "Запись",
    AppState.TRANSCRIBING: "Распознаю",
    AppState.PROCESSING: "Очищаю",
    AppState.PASTING: "Вставляю",
    AppState.ERROR: "Ошибка",
    AppState.PAUSED: "Пауза",
}

#: Разрешённые переходы. Ошибка и пауза достижимы из любого состояния.
_TRANSITIONS: dict[AppState, frozenset[AppState]] = {
    AppState.IDLE: frozenset({AppState.LISTENING, AppState.RECORDING}),
    AppState.LISTENING: frozenset({AppState.IDLE, AppState.RECORDING}),
    AppState.RECORDING: frozenset({AppState.IDLE, AppState.LISTENING, AppState.TRANSCRIBING}),
    # Обработка пропускается в режиме «сырой текст» и когда она отключена,
    # поэтому переход сразу к вставке разрешён.
    AppState.TRANSCRIBING: frozenset(
        {AppState.IDLE, AppState.LISTENING, AppState.PROCESSING, AppState.PASTING}
    ),
    AppState.PROCESSING: frozenset({AppState.IDLE, AppState.LISTENING, AppState.PASTING}),
    AppState.PASTING: frozenset({AppState.IDLE, AppState.LISTENING}),
    AppState.ERROR: frozenset({AppState.IDLE, AppState.LISTENING}),
    AppState.PAUSED: frozenset({AppState.IDLE, AppState.LISTENING}),
}

#: Состояния, в которые можно попасть откуда угодно.
_ALWAYS_REACHABLE: frozenset[AppState] = frozenset({AppState.ERROR, AppState.PAUSED})

#: Во время этих состояний детектор голосовой команды должен молчать.
BUSY_STATES: frozenset[AppState] = frozenset(
    {
        AppState.RECORDING,
        AppState.TRANSCRIBING,
        AppState.PROCESSING,
        AppState.PASTING,
    }
)


class InvalidTransitionError(RuntimeError):
    """Попытка выполнить переход, не описанный в таблице."""

    def __init__(self, current: AppState, target: AppState) -> None:
        super().__init__(f"Переход {current.value} -> {target.value} не разрешён")
        self.current = current
        self.target = target


class StateMachine:
    """Потокобезопасная машина состояний.

    Слушатели вызываются вне блокировки, поэтому обработчик может безопасно
    читать текущее состояние.
    """

    def __init__(self, initial: AppState = AppState.IDLE) -> None:
        self._lock = threading.RLock()
        self._state = initial
        self._listeners: list[Callable[[AppState, AppState, str], None]] = []

    @property
    def state(self) -> AppState:
        with self._lock:
            return self._state

    @property
    def is_busy(self) -> bool:
        """Идёт запись или обработка — новые запуски игнорируются."""
        return self.state in BUSY_STATES

    def add_listener(self, listener: Callable[[AppState, AppState, str], None]) -> None:
        with self._lock:
            self._listeners.append(listener)

    def can(self, target: AppState) -> bool:
        with self._lock:
            return self._can_locked(self._state, target)

    @staticmethod
    def _can_locked(current: AppState, target: AppState) -> bool:
        if target is current:
            return True
        if target in _ALWAYS_REACHABLE:
            return True
        return target in _TRANSITIONS[current]

    def to(self, target: AppState, detail: str = "") -> bool:
        """Выполняет переход. Возвращает ``False``, если состояние не изменилось."""
        with self._lock:
            current = self._state
            if not self._can_locked(current, target):
                raise InvalidTransitionError(current, target)
            if target is current:
                return False
            self._state = target
            listeners = list(self._listeners)

        logger.debug(
            "Состояние: %s -> %s%s",
            current.value,
            target.value,
            f" ({detail})" if detail else "",
        )
        for listener in listeners:
            try:
                listener(current, target, detail)
            except Exception:
                logger.exception("Слушатель состояния завершился ошибкой")
        return True

    def reset(self, detail: str = "") -> bool:
        """Безусловный возврат в исходное состояние после сбоя или отмены."""
        with self._lock:
            current = self._state
            if current is AppState.IDLE:
                return False
            self._state = AppState.IDLE
            listeners = list(self._listeners)

        logger.debug(
            "Состояние: %s -> idle (сброс%s)",
            current.value,
            f": {detail}" if detail else "",
        )
        for listener in listeners:
            try:
                listener(current, AppState.IDLE, detail)
            except Exception:
                logger.exception("Слушатель состояния завершился ошибкой")
        return True
