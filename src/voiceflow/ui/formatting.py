"""Приведение чисел к виду, понятному человеку.

Живёт отдельно, потому что нужно и мастеру первого запуска, и вкладке
«Модели»: дублировать форматирование в двух местах нельзя.
"""

from __future__ import annotations


def human_size(size_bytes: int) -> str:
    """Размер файла или каталога."""
    if size_bytes >= 1024**3:
        return f"{size_bytes / 1024**3:.1f} ГБ"
    if size_bytes >= 1024**2:
        return f"{size_bytes / 1024**2:.0f} МБ"
    return f"{size_bytes / 1024:.0f} КБ"


def human_duration(milliseconds: int) -> str:
    """Длительность записи или обработки."""
    seconds = milliseconds / 1000
    if seconds < 60:
        return f"{seconds:.1f} с"
    minutes, rest = divmod(int(seconds), 60)
    return f"{minutes} мин {rest} с"
