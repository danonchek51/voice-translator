"""Запуск боковой кнопкой мыши.

Удержание боковой кнопки — самый надёжный способ запуска: он не зависит от
раскладки, не конфликтует с горячими клавишами приложений и не требует
постоянно открытого микрофона.

Слушатель не подавляет события, поэтому обычные щелчки продолжают работать
в других программах.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

#: Имена кнопок из настроек в имена ``pynput``.
BUTTON_NAMES: dict[str, str] = {
    "x1": "x1",
    "x2": "x2",
    "middle": "middle",
}

BUTTON_LABELS: dict[str, str] = {
    "none": "не используется",
    "x1": "боковая кнопка «назад»",
    "x2": "боковая кнопка «вперёд»",
    "middle": "средняя кнопка",
}


class MouseButtonListener:
    """Слушатель одной кнопки мыши с событиями нажатия и отпускания."""

    def __init__(
        self,
        button: str,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
    ) -> None:
        self._button = button
        self._on_press = on_press
        self._on_release = on_release
        self._listener: object | None = None
        self._target: object | None = None

    @property
    def is_running(self) -> bool:
        return self._listener is not None

    @property
    def description(self) -> str:
        return BUTTON_LABELS.get(self._button, self._button)

    def start(self) -> bool:
        if self._listener is not None:
            return True
        if self._button not in BUTTON_NAMES:
            if self._button != "none":
                logger.warning("Неизвестная кнопка мыши: %s", self._button)
            return False

        try:
            from pynput import mouse
        except ImportError:
            logger.warning("pynput не установлен, кнопка мыши недоступна")
            return False

        target = getattr(mouse.Button, BUTTON_NAMES[self._button], None)
        if target is None:
            logger.warning(
                "Кнопка %s не поддерживается этой сборкой pynput", self._button
            )
            return False
        self._target = target

        try:
            listener = mouse.Listener(on_click=self._handle_click)
            listener.start()
        except Exception:
            logger.exception("Не удалось установить перехват мыши")
            return False

        self._listener = listener
        logger.info("Запуск по кнопке мыши активен: %s", self.description)
        return True

    def stop(self) -> None:
        listener = self._listener
        self._listener = None
        if listener is None:
            return
        try:
            listener.stop()  # type: ignore[attr-defined]
        except Exception:
            logger.exception("Ошибка при снятии перехвата мыши")

    def _handle_click(self, x: int, y: int, button: object, pressed: bool) -> None:
        if button is not self._target:
            return
        callback = self._on_press if pressed else self._on_release
        try:
            callback()
        except Exception:
            logger.exception("Ошибка в обработчике кнопки мыши")
