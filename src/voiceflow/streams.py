"""Заглушки потоков вывода для сборки без консоли.

PyInstaller в режиме ``--windowed`` не создаёт консоль, и тогда ``sys.stdout``
с ``sys.stderr`` равны ``None``. Любая библиотека, которая пишет прогресс или
предупреждение, падает на этом с ``AttributeError: 'NoneType' object has no
attribute 'write'`` — и ошибка выглядит как сбой загрузки модели, хотя дело
вовсе не в ней.

Поэтому при старте потоки подменяются на заглушки: приложение всё равно ведёт
собственный журнал, а вывод в никуда безопаснее отсутствующего потока.
"""

from __future__ import annotations

import sys
from typing import TextIO


class NullStream:
    """Поток, который молча всё принимает."""

    encoding = "utf-8"
    errors = "replace"

    def write(self, text: str) -> int:
        return len(text)

    def writelines(self, lines: object) -> None:
        return None

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return False

    def fileno(self) -> int:
        # Некоторые библиотеки спрашивают номер дескриптора; честно сообщаем,
        # что его нет, вместо выдачи чужого номера.
        raise OSError("поток без файлового дескриптора")

    def close(self) -> None:
        return None

    @property
    def closed(self) -> bool:
        return False


def ensure_output_streams() -> list[str]:
    """Подставляет заглушки вместо отсутствующих потоков.

    Возвращает имена подменённых потоков — их полезно записать в журнал.
    """
    replaced: list[str] = []
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            setattr(sys, name, NullStream())
            replaced.append(name)
    return replaced


def stream_or_null(name: str) -> TextIO:
    """Существующий поток или заглушка. Для настройки журнала."""
    stream = getattr(sys, name, None)
    if stream is None:
        return NullStream()  # type: ignore[return-value]
    return stream
