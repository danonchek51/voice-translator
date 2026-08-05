"""Превращение нажатий в команды записи.

Логика режимов Toggle и Hold платформонезависима, поэтому живёт в ядре.
Слушатели клавиатуры и мыши только сообщают «нажали» и «отпустили».

Добавление нового способа запуска — это новый источник в :class:`TriggerSource`
и новый слушатель в платформенном слое. Машина состояний при этом не меняется.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from enum import Enum

logger = logging.getLogger(__name__)

#: Более короткое удержание считаем случайным щелчком и отменяем запись.
MIN_HOLD_SECONDS = 0.25


class TriggerSource(Enum):
    """Откуда пришла команда."""

    HOTKEY = "hotkey"
    MOUSE = "mouse"
    TRAY = "tray"
    OVERLAY = "overlay"
    VOICE = "voice"


#: Источники, у которых нет «отпускания»: пункт меню и голосовая фраза
#: срабатывают один раз, их нельзя «удерживать» как кнопку мыши.
CLICK_ONLY_SOURCES = frozenset(
    {TriggerSource.TRAY, TriggerSource.OVERLAY, TriggerSource.VOICE}
)


class TriggerAction(Enum):
    NONE = "none"
    START = "start"
    STOP = "stop"
    #: Запись отменяется без обработки: удержание было слишком коротким.
    CANCEL = "cancel"


class TriggerCoordinator:
    """Решает, что делать при нажатии и отпускании.

    Потокобезопасен: слушатели клавиатуры и мыши работают в своих потоках.
    """

    def __init__(
        self,
        mode_provider: Callable[[], str],
        recording_provider: Callable[[], bool],
        clock: Callable[[], float] = time.monotonic,
        min_hold_seconds: float = MIN_HOLD_SECONDS,
    ) -> None:
        self._mode_provider = mode_provider
        self._recording_provider = recording_provider
        self._clock = clock
        self._min_hold_seconds = min_hold_seconds
        self._lock = threading.RLock()
        self._holding_source: TriggerSource | None = None
        self._hold_started_at = 0.0

    @property
    def is_holding(self) -> bool:
        with self._lock:
            return self._holding_source is not None

    def press(self, source: TriggerSource) -> TriggerAction:
        """Обрабатывает нажатие."""
        with self._lock:
            if self._is_hold_mode(source):
                if self._holding_source is not None:
                    # Повторное нажатие при зажатой кнопке — автоповтор клавиши.
                    return TriggerAction.NONE
                if self._recording_provider():
                    return TriggerAction.NONE
                self._holding_source = source
                self._hold_started_at = self._clock()
                return TriggerAction.START

            if self._recording_provider():
                return TriggerAction.STOP
            return TriggerAction.START

    def release(self, source: TriggerSource) -> TriggerAction:
        """Обрабатывает отпускание. Значимо только в режиме удержания."""
        with self._lock:
            if self._holding_source is not source:
                return TriggerAction.NONE

            held = self._clock() - self._hold_started_at
            self._holding_source = None
            self._hold_started_at = 0.0

            if not self._recording_provider():
                return TriggerAction.NONE
            if held < self._min_hold_seconds:
                logger.debug("Удержание %.0f мс — считаю случайным щелчком", held * 1000)
                return TriggerAction.CANCEL
            return TriggerAction.STOP

    def reset(self) -> None:
        """Сбрасывает состояние удержания: например, при потере фокуса ввода."""
        with self._lock:
            self._holding_source = None
            self._hold_started_at = 0.0

    def _is_hold_mode(self, source: TriggerSource) -> bool:
        if source in CLICK_ONLY_SOURCES:
            return False
        return self._mode_provider() == "hold"
