"""Настройка логирования.

Два правила, которые нельзя нарушать:

* распознанный текст не попадает в лог, пока пользователь явно не включил
  отладочный флаг ``system.log_user_text``;
* лог не растёт бесконечно — пять файлов по два мегабайта.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from voiceflow import paths

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)-38s %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

MAX_BYTES = 2 * 1024 * 1024
BACKUP_COUNT = 5

#: Ключ в ``extra``, помечающий запись как содержащую речь пользователя.
USER_TEXT_KEY = "user_text"

_user_text_allowed = False


class UserTextFilter(logging.Filter):
    """Вырезает записи с речью пользователя, если отладка не включена."""

    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, USER_TEXT_KEY, False) and not _user_text_allowed:
            return False
        return True


def set_user_text_logging(enabled: bool) -> None:
    """Разрешает или запрещает запись распознанного текста в лог."""
    global _user_text_allowed
    _user_text_allowed = enabled


def user_text_logging_enabled() -> bool:
    return _user_text_allowed


def log_user_text(logger: logging.Logger, message: str, text: str) -> None:
    """Пишет распознанный текст только при включённой отладке."""
    logger.debug("%s: %s", message, text, extra={USER_TEXT_KEY: True})


def setup_logging(
    level: str = "INFO",
    log_file: Path | None = None,
    console: bool = True,
) -> Path | None:
    """Настраивает корневой логгер. Возвращает путь к файлу лога."""
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    text_filter = UserTextFilter()
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    target = log_file
    if target is None:
        try:
            paths.logs_dir().mkdir(parents=True, exist_ok=True)
            target = paths.logs_dir() / "app.log"
        except OSError:
            target = None

    if target is not None:
        try:
            file_handler = logging.handlers.RotatingFileHandler(
                target,
                maxBytes=MAX_BYTES,
                backupCount=BACKUP_COUNT,
                encoding="utf-8",
            )
            file_handler.setLevel(numeric_level)
            file_handler.setFormatter(formatter)
            file_handler.addFilter(text_filter)
            root.addHandler(file_handler)
        except OSError:
            target = None

    if console:
        stream = logging.StreamHandler(sys.stderr)
        stream.setLevel(numeric_level)
        stream.setFormatter(formatter)
        stream.addFilter(text_filter)
        root.addHandler(stream)

    # Сторонние библиотеки слишком разговорчивы на уровне DEBUG.
    for noisy in ("httpx", "httpcore", "urllib3", "numba", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return target
