"""Расположение моделей и офлайн-режим.

Основной режим работы обязан обходиться без интернета. Библиотеки загрузки
моделей по умолчанию лезут в сеть при каждом обращении, поэтому приложение
принудительно переводит их в офлайн и снимает запрет только на время явной
загрузки, запущенной пользователем.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from voiceflow import paths

logger = logging.getLogger(__name__)

#: Переменные, которыми управляем. Значения пользователя не трогаем, если он
#: выставил их сам — это способ подключить общий кэш моделей.
_HF_HOME = "HF_HOME"
_HF_HUB_CACHE = "HF_HUB_CACHE"
_HF_OFFLINE = "HF_HUB_OFFLINE"
_TRANSFORMERS_OFFLINE = "TRANSFORMERS_OFFLINE"


def configure_offline_cache() -> None:
    """Направляет кэш моделей в каталог приложения и включает офлайн-режим."""
    if not os.environ.get(_HF_HOME):
        os.environ[_HF_HOME] = str(paths.hf_cache_dir())
    if not os.environ.get(_HF_HUB_CACHE):
        os.environ[_HF_HUB_CACHE] = str(paths.hf_cache_dir() / "hub")
    os.environ[_HF_OFFLINE] = "1"
    os.environ[_TRANSFORMERS_OFFLINE] = "1"
    logger.debug("Кэш моделей: %s (офлайн)", os.environ[_HF_HOME])


def is_offline() -> bool:
    return os.environ.get(_HF_OFFLINE) == "1"


def hub_cache_root() -> Path:
    """Каталог кэша Hugging Face."""
    override = os.environ.get(_HF_HUB_CACHE)
    if override:
        return Path(override)
    home = os.environ.get(_HF_HOME)
    if home:
        return Path(home) / "hub"
    return paths.hf_cache_dir() / "hub"


def repo_snapshots(repo_id: str) -> list[Path]:
    """Каталоги загруженных версий репозитория.

    ``snapshot_download(local_files_only=True)`` здесь не подходит: он требует
    полного зеркала репозитория, а модели скачиваются выборочно, только нужными
    файлами. Поэтому смотрим прямо в раскладку кэша.
    """
    folder = hub_cache_root() / f"models--{repo_id.replace('/', '--')}" / "snapshots"
    if not folder.is_dir():
        return []
    return [item for item in folder.iterdir() if item.is_dir()]


def repo_has_files(repo_id: str, patterns: Sequence[str]) -> bool:
    """Есть ли в кэше все указанные файлы хотя бы одной версии репозитория."""
    if not patterns:
        return False
    for snapshot in repo_snapshots(repo_id):
        if all(any(snapshot.glob(pattern)) for pattern in patterns):
            return True
    return False


@contextmanager
def allow_downloads() -> Iterator[None]:
    """Временно разрешает сеть. Используется только менеджером моделей."""
    previous = {
        name: os.environ.get(name) for name in (_HF_OFFLINE, _TRANSFORMERS_OFFLINE)
    }
    for name in previous:
        os.environ.pop(name, None)
    logger.info("Загрузка моделей: сеть временно разрешена")
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ[name] = "1"
            else:
                os.environ[name] = value
        logger.info("Загрузка моделей завершена, офлайн-режим восстановлен")
