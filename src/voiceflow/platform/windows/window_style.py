"""Настройка стилей окна через Win32.

Плашка обязана оставаться видимой поверх других окон, но никогда не забирать
у них фокус: пользователь диктует прямо в редактор, и потеря фокуса ломает
весь сценарий. Флагов Qt для этого недостаточно, нужен ``WS_EX_NOACTIVATE``.
"""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

logger = logging.getLogger(__name__)

GWL_EXSTYLE = -20

WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000

# Отдельный экземпляр библиотеки: общий ctypes.windll кэширует указатели на
# функции, и заданные ниже argtypes повлияли бы на другие библиотеки в
# процессе. use_last_error включает сохранение кода ошибки Windows.
_user32 = ctypes.WinDLL("user32", use_last_error=True)

# На 64-битной системе нужны Ptr-варианты, иначе стиль обрезается до 32 бит.
if hasattr(_user32, "GetWindowLongPtrW"):
    _get_window_long = _user32.GetWindowLongPtrW
    _set_window_long = _user32.SetWindowLongPtrW
    _get_window_long.restype = ctypes.c_ssize_t
    _set_window_long.restype = ctypes.c_ssize_t
    _get_window_long.argtypes = [wintypes.HWND, ctypes.c_int]
    _set_window_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
else:  # pragma: no cover - только 32-битный Python
    _get_window_long = _user32.GetWindowLongW
    _set_window_long = _user32.SetWindowLongW
    _get_window_long.restype = wintypes.LONG
    _set_window_long.restype = wintypes.LONG
    _get_window_long.argtypes = [wintypes.HWND, ctypes.c_int]
    _set_window_long.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]


class WindowsWindowStyler:
    """Реализация :class:`~voiceflow.platform.base.WindowStyler` для Windows."""

    def make_non_activating(self, window_handle: int) -> bool:
        return self._add_ex_style(window_handle, WS_EX_NOACTIVATE)

    def exclude_from_taskbar(self, window_handle: int) -> bool:
        if not self._add_ex_style(window_handle, WS_EX_TOOLWINDOW):
            return False
        return self._remove_ex_style(window_handle, WS_EX_APPWINDOW)

    def _add_ex_style(self, window_handle: int, flag: int) -> bool:
        return self._update_ex_style(window_handle, lambda style: style | flag)

    def _remove_ex_style(self, window_handle: int, flag: int) -> bool:
        return self._update_ex_style(window_handle, lambda style: style & ~flag)

    @staticmethod
    def _update_ex_style(window_handle: int, transform) -> bool:  # type: ignore[no-untyped-def]
        if not window_handle:
            return False
        try:
            hwnd = wintypes.HWND(window_handle)
            current = _get_window_long(hwnd, GWL_EXSTYLE)
            updated = transform(current)
            if updated == current:
                return True
            ctypes.set_last_error(0)
            result = _set_window_long(hwnd, GWL_EXSTYLE, updated)
            if result == 0 and ctypes.get_last_error() != 0:
                logger.warning(
                    "SetWindowLongPtr не изменил стиль окна: код %s",
                    ctypes.get_last_error(),
                )
                return False
            return True
        except Exception:
            logger.exception("Не удалось изменить расширенный стиль окна")
            return False
