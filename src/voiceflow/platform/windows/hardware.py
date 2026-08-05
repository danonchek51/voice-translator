"""Сведения о железе для подбора конфигурации.

Нужны ровно три вещи: сколько оперативной памяти, сколько ядер и есть ли
видеокарта с достаточной памятью. По ним приложение само предлагает пресет,
чтобы человек не выбирал вслепую между «Лёгким» и «Качеством».

Спрашиваем систему напрямую, без внешних пакетов: лишняя зависимость ради
одного числа увеличит сборку и добавит поводов для отказа.
"""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

logger = logging.getLogger(__name__)

#: Ветка реестра с описанием видеоадаптеров.
_DISPLAY_CLASS = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"

#: Производители, чьи видеокарты дают ускорение нашим моделям.
_ACCELERATED = ("nvidia", "amd", "radeon", "intel arc")


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = (
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    )


def total_memory_bytes() -> int:
    """Объём оперативной памяти. Ноль означает «узнать не удалось»."""
    try:
        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return 0
        return int(status.ullTotalPhys)
    except Exception:
        logger.debug("Не удалось узнать объём памяти", exc_info=True)
        return 0


def video_adapter() -> tuple[str, int]:
    """Название видеокарты и её память в байтах.

    Читается из реестра: обращение к DirectX ради двух чисел потребовало бы
    работы с COM, а свойства адаптера система и так там хранит.
    """
    try:
        import winreg
    except ImportError:
        return "", 0

    best_name = ""
    best_memory = 0
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _DISPLAY_CLASS) as root:
            index = 0
            while True:
                try:
                    subkey = winreg.EnumKey(root, index)
                except OSError:
                    break
                index += 1
                if not subkey.isdigit():
                    continue
                name, memory = _read_adapter(winreg, root, subkey)
                # Берём адаптер с наибольшей памятью: у ноутбуков рядом со
                # встроенным видеоядром стоит дискретная карта, нужна она.
                if memory > best_memory or (memory == best_memory and not best_name):
                    best_name, best_memory = name or best_name, memory
    except OSError:
        logger.debug("Сведения о видеокарте недоступны", exc_info=True)
    return best_name, best_memory


def _read_adapter(winreg, root, subkey: str) -> tuple[str, int]:  # type: ignore[no-untyped-def]
    try:
        with winreg.OpenKey(root, subkey) as key:
            name = _value(winreg, key, "DriverDesc")
            memory = _value(winreg, key, "HardwareInformation.qwMemorySize")
            if not isinstance(memory, int):
                memory = 0
            return (name if isinstance(name, str) else ""), int(memory)
    except OSError:
        return "", 0


def _value(winreg, key, name: str):  # type: ignore[no-untyped-def]
    try:
        value, _ = winreg.QueryValueEx(key, name)
    except OSError:
        return None
    return value


def has_accelerated_gpu(name: str) -> bool:
    """Похоже ли устройство на видеокарту, которая ускорит модели."""
    lowered = name.lower()
    return any(vendor in lowered for vendor in _ACCELERATED)
