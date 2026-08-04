"""Глобальная горячая клавиша.

``pynput`` ставит низкоуровневый перехват ``WH_KEYBOARD_LL``. Готовый класс
``GlobalHotKeys`` сообщает только о срабатывании, а для режима удержания нужны
оба события, поэтому состояние комбинации отслеживается вручную.

Известное ограничение Windows: процесс без повышенных прав не получает
события, пока активно окно, запущенное от администратора. Резервные способы
запуска (кнопка мыши, меню трея) в этот момент тоже не сработают, зато
работает голосовая активация.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)


class HotkeyListener:
    """Слушатель одной комбинации клавиш с событиями нажатия и отпускания."""

    def __init__(
        self,
        combination: str,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
    ) -> None:
        self._combination = combination
        self._on_press = on_press
        self._on_release = on_release
        self._listener: object | None = None
        self._expected: frozenset[object] = frozenset()
        self._pressed: set[object] = set()
        self._active = False

    @property
    def is_running(self) -> bool:
        return self._listener is not None

    @property
    def description(self) -> str:
        return self._combination

    def start(self) -> bool:
        if self._listener is not None:
            return True
        if not self._combination.strip():
            logger.info("Горячая клавиша не задана, слушатель не запускается")
            return False

        try:
            from pynput import keyboard
        except ImportError:
            logger.warning("pynput не установлен, горячая клавиша недоступна")
            return False

        try:
            self._expected = frozenset(keyboard.HotKey.parse(self._combination))
        except ValueError:
            logger.error(
                "Не удалось разобрать комбинацию «%s». "
                "Ожидается запись вида <ctrl>+<alt>+d",
                self._combination,
            )
            return False

        try:
            listener = keyboard.Listener(
                on_press=self._handle_press,
                on_release=self._handle_release,
            )
            listener.start()
        except Exception:
            logger.exception("Не удалось установить перехват клавиатуры")
            return False

        self._listener = listener
        self._pressed.clear()
        self._active = False
        logger.info("Горячая клавиша активна: %s", self._combination)
        return True

    def stop(self) -> None:
        listener = self._listener
        self._listener = None
        self._pressed.clear()
        self._active = False
        if listener is None:
            return
        try:
            listener.stop()  # type: ignore[attr-defined]
        except Exception:
            logger.exception("Ошибка при снятии перехвата клавиатуры")

    # ------------------------------------------------------------------ #
    # Обработка событий слушателя
    # ------------------------------------------------------------------ #

    def _canonical(self, key: object) -> object:
        listener = self._listener
        if listener is None:
            return key
        try:
            return listener.canonical(key)  # type: ignore[attr-defined]
        except Exception:
            return key

    def _handle_press(self, key: object) -> None:
        canonical = self._canonical(key)
        if canonical not in self._expected:
            return
        self._pressed.add(canonical)
        if self._active or self._pressed < self._expected:
            return
        self._active = True
        self._safe_call(self._on_press, "нажатия")

    def _handle_release(self, key: object) -> None:
        canonical = self._canonical(key)
        if canonical not in self._expected:
            return
        self._pressed.discard(canonical)
        if not self._active:
            return
        self._active = False
        self._safe_call(self._on_release, "отпускания")

    @staticmethod
    def _safe_call(callback: Callable[[], None], what: str) -> None:
        """Исключение в обработчике не должно убивать перехват клавиатуры."""
        try:
            callback()
        except Exception:
            logger.exception("Ошибка в обработчике %s горячей клавиши", what)
