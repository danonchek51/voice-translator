"""Активное окно Windows.

Окно запоминается в момент начала записи, а не в конце: за время диктовки
и обработки пользователь может переключиться, и текст улетел бы не туда.

Возврат фокуса — самая капризная часть. ``SetForegroundWindow`` система
разрешает не всегда: право переводить окно на передний план есть только
у процесса, который последним получал ввод. Обходной приём с
``AttachThreadInput`` временно объединяет очереди ввода и снимает запрет.
Если и это не сработало, вставка не выполняется, а текст остаётся в буфере.
"""

from __future__ import annotations

import ctypes
import logging
from pathlib import Path

import win32api
import win32con
import win32gui
import win32process

from voiceflow.platform.base import WindowInfo

logger = logging.getLogger(__name__)

#: Разрешить любому процессу перевести окно на передний план.
ASFW_ANY = -1

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# AllowSetForegroundWindow в pywin32 не обёрнута, поэтому вызываем напрямую.
# Отдельный экземпляр библиотеки — чтобы не трогать общий кэш ctypes.windll.
_user32 = ctypes.WinDLL("user32", use_last_error=True)


class WindowsForegroundWindows:
    """Реализация :class:`~voiceflow.platform.base.ForegroundWindows`."""

    def current(self) -> WindowInfo | None:
        try:
            handle = win32gui.GetForegroundWindow()
        except Exception:
            logger.exception("Не удалось получить активное окно")
            return None
        if not handle:
            return None
        return WindowInfo(
            handle=int(handle),
            title=self._title(handle),
            process_name=self._process_name(handle),
        )

    def exists(self, handle: int) -> bool:
        if not handle:
            return False
        try:
            return bool(win32gui.IsWindow(handle))
        except Exception:
            return False

    def is_active(self, handle: int) -> bool:
        try:
            return bool(handle) and int(win32gui.GetForegroundWindow()) == int(handle)
        except Exception:
            return False

    def activate(self, handle: int) -> bool:
        if not self.exists(handle):
            logger.info("Целевое окно уже закрыто")
            return False
        if self.is_active(handle):
            return True

        self._restore_if_minimized(handle)

        try:
            _user32.AllowSetForegroundWindow(ASFW_ANY)
        except Exception:
            logger.debug("AllowSetForegroundWindow недоступна", exc_info=True)

        if self._try_set_foreground(handle):
            return True
        if self._try_set_foreground_attached(handle):
            return True

        logger.warning(
            "Система не разрешила вернуть фокус окну %s: вставка невозможна", handle
        )
        return False

    # ------------------------------------------------------------------ #
    # Внутреннее
    # ------------------------------------------------------------------ #

    @staticmethod
    def _title(handle: int) -> str:
        try:
            return str(win32gui.GetWindowText(handle))
        except Exception:
            return ""

    @staticmethod
    def _process_name(handle: int) -> str:
        try:
            _, pid = win32process.GetWindowThreadProcessId(handle)
        except Exception:
            return ""
        process = None
        try:
            process = win32api.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            full_path = win32process.GetModuleFileNameEx(process, 0)
            return Path(str(full_path)).name
        except Exception:
            # Для окон системных и защищённых процессов имя недоступно —
            # это нормально, оно используется только для сообщений.
            return ""
        finally:
            if process is not None:
                try:
                    win32api.CloseHandle(process)
                except Exception:
                    logger.debug("Не удалось закрыть дескриптор процесса", exc_info=True)

    @staticmethod
    def _restore_if_minimized(handle: int) -> None:
        try:
            if win32gui.IsIconic(handle):
                win32gui.ShowWindow(handle, win32con.SW_RESTORE)
        except Exception:
            logger.debug("Не удалось развернуть свёрнутое окно", exc_info=True)

    @staticmethod
    def _try_set_foreground(handle: int) -> bool:
        try:
            win32gui.SetForegroundWindow(handle)
        except Exception:
            return False
        return int(win32gui.GetForegroundWindow()) == int(handle)

    def _try_set_foreground_attached(self, handle: int) -> bool:
        """Присоединяется к очереди ввода активного окна и повторяет попытку."""
        try:
            foreground = win32gui.GetForegroundWindow()
            target_thread, _ = win32process.GetWindowThreadProcessId(handle)
            foreground_thread, _ = win32process.GetWindowThreadProcessId(foreground)
            current_thread = win32api.GetCurrentThreadId()
        except Exception:
            logger.debug("Не удалось определить потоки окон", exc_info=True)
            return False

        attached_foreground = self._attach(current_thread, foreground_thread)
        attached_target = self._attach(current_thread, target_thread)
        try:
            return self._try_set_foreground(handle)
        finally:
            if attached_target:
                self._detach(current_thread, target_thread)
            if attached_foreground:
                self._detach(current_thread, foreground_thread)

    @staticmethod
    def _attach(source: int, target: int) -> bool:
        # Присоединять поток к самому себе нельзя: система вернёт ошибку 87.
        if not target or source == target:
            return False
        try:
            win32process.AttachThreadInput(source, target, True)
        except Exception:
            logger.debug("AttachThreadInput не сработала", exc_info=True)
            return False
        return True

    @staticmethod
    def _detach(source: int, target: int) -> None:
        try:
            win32process.AttachThreadInput(source, target, False)
        except Exception:
            logger.debug("Не удалось отсоединить очередь ввода", exc_info=True)
