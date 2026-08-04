"""Защита от второго запущенного экземпляра.

Две копии приложения дрались бы за микрофон и за глобальные горячие клавиши,
а пользователь видел бы две плашки. Именованный мьютекс снимается системой
автоматически, даже если процесс завершился аварийно.
"""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

logger = logging.getLogger(__name__)

ERROR_ALREADY_EXISTS = 183

# use_last_error обязателен: без него ctypes.get_last_error() всегда вернёт
# ноль, и повторный запуск приложения не будет обнаружен. Отдельный экземпляр
# библиотеки нужен, чтобы заданные здесь argtypes не влияли на чужой код.
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CreateMutexW.argtypes = [wintypes.LPCVOID, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


class SingleInstanceGuard:
    """Держит именованный мьютекс, пока приложение работает."""

    def __init__(self, name: str = "VoiceFlow.SingleInstance") -> None:
        # Префикс Local\ ограничивает область текущей сессией пользователя:
        # в терминальной сессии у каждого пользователя своя копия.
        self._name = f"Local\\{name}"
        self._handle: int | None = None
        self._acquired = False

    @property
    def acquired(self) -> bool:
        return self._acquired

    def acquire(self) -> bool:
        """Пытается занять мьютекс. ``False`` — приложение уже запущено."""
        try:
            handle = _kernel32.CreateMutexW(None, True, self._name)
        except OSError:
            logger.exception("Не удалось создать мьютекс единственного экземпляра")
            self._acquired = True
            return True

        if not handle:
            logger.warning("CreateMutexW вернул пустой дескриптор, проверку пропускаю")
            self._acquired = True
            return True

        self._handle = handle
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            self._acquired = False
            return False

        self._acquired = True
        return True

    def release(self) -> None:
        if self._handle:
            try:
                _kernel32.CloseHandle(self._handle)
            except OSError:
                logger.exception("Не удалось освободить мьютекс")
            self._handle = None
        self._acquired = False

    def __enter__(self) -> bool:
        return self.acquire()

    def __exit__(self, *exc_info: object) -> None:
        self.release()
