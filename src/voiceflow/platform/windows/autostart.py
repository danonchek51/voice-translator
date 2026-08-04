"""Автозапуск вместе с Windows через ключ HKCU\\...\\Run.

Ветка текущего пользователя выбрана намеренно: она не требует прав
администратора и не показывает запрос UAC. Режим повышенных прав через
Планировщик — отдельная задача и включается осознанно.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "VoiceFlow"


def _launch_command() -> str:
    """Команда запуска с учётом того, собрано приложение или запущено из исходников."""
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}"'
    return f'"{sys.executable}" -m voiceflow'


class WindowsAutostart:
    """Чтение и запись значения автозапуска в реестре."""

    @property
    def is_supported(self) -> bool:
        return True

    @property
    def description(self) -> str:
        return "Запись в HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run"

    def is_enabled(self) -> bool:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                winreg.QueryValueEx(key, VALUE_NAME)
        except FileNotFoundError:
            return False
        except OSError:
            logger.exception("Не удалось прочитать ключ автозапуска")
            return False
        return True

    def set_enabled(self, enabled: bool) -> bool:
        """``False`` означает, что реестр отказал; настройку менять нельзя."""
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
            ) as key:
                if enabled:
                    winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, _launch_command())
                else:
                    try:
                        winreg.DeleteValue(key, VALUE_NAME)
                    except FileNotFoundError:
                        # Значения и так нет — это уже нужное состояние.
                        pass
        except OSError:
            logger.exception("Не удалось изменить автозапуск")
            return False

        logger.info("Автозапуск %s", "включён" if enabled else "выключен")
        return True
