"""Миграции файла настроек между версиями схемы.

Правила:

* каждая функция поднимает версию ровно на единицу;
* функция работает со словарём, а не с dataclass, — она должна уметь читать
  формат, которого в текущем коде уже нет;
* неизвестные ключи не удаляются: пользователь может откатиться на предыдущую
  версию приложения, и его настройки не должны пропасть.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from voiceflow.core.settings.schema import CURRENT_SCHEMA_VERSION

logger = logging.getLogger(__name__)

Migration = Callable[[dict[str, Any]], dict[str, Any]]


def _migrate_0_to_1(data: dict[str, Any]) -> dict[str, Any]:
    """Ранний прототип хранил часть ключей плоским списком в корне файла."""
    moved: dict[str, tuple[str, str]] = {
        "wake_phrase": ("activation", "wake_phrase"),
        "stop_phrase": ("activation", "stop_phrase"),
        "hotkey": ("activation", "hotkey"),
        "auto_paste": ("output", "auto_paste"),
        "paste_delay_ms": ("output", "paste_delay_ms"),
        "device_name": ("audio", "device_name"),
        "history_enabled": ("history", "enabled"),
        "history_limit": ("history", "max_entries"),
    }
    result = dict(data)
    for old_key, (section, new_key) in moved.items():
        if old_key not in result:
            continue
        value = result.pop(old_key)
        section_data = result.get(section)
        if not isinstance(section_data, dict):
            section_data = {}
        section_data.setdefault(new_key, value)
        result[section] = section_data
    result["schema_version"] = 1
    return result


def _migrate_1_to_2(data: dict[str, Any]) -> dict[str, Any]:
    """Выбор режима заменён цепочкой шагов с галочками.

    Прежний ``default_mode`` переносим в флаги, чтобы поведение не изменилось
    у тех, кто уже выбрал режим: «перевод» включает перевод, «инструкция» —
    инструкцию, «сырой текст» выключает всё.
    """
    result = dict(data)
    processing = result.get("processing")
    if not isinstance(processing, dict):
        result["schema_version"] = 2
        return result

    processing = dict(processing)
    mode = processing.pop("default_mode", None)

    if isinstance(mode, str):
        if mode == "raw":
            processing["clean_enabled"] = False
            processing["translate_enabled"] = False
            processing["prompt_mode_enabled"] = False
        elif mode == "translate":
            processing.setdefault("clean_enabled", True)
            processing["translate_enabled"] = True
            processing["prompt_mode_enabled"] = False
        elif mode == "prompt":
            processing.setdefault("clean_enabled", True)
            processing["translate_enabled"] = False
            processing["prompt_mode_enabled"] = True
        elif mode == "clean":
            processing["clean_enabled"] = True
            processing["translate_enabled"] = False
            processing["prompt_mode_enabled"] = False

    result["processing"] = processing
    result["schema_version"] = 2
    return result


#: Ключ — версия, из которой поднимаемся.
MIGRATIONS: dict[int, Migration] = {
    0: _migrate_0_to_1,
    1: _migrate_1_to_2,
}


def detect_version(data: dict[str, Any]) -> int:
    """Версия файла. Отсутствие поля означает нулевую версию."""
    raw = data.get("schema_version")
    if isinstance(raw, int) and raw >= 0:
        return raw
    return 0


def needs_migration(data: dict[str, Any]) -> bool:
    return detect_version(data) < CURRENT_SCHEMA_VERSION


def migrate(data: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Прогоняет цепочку миграций до текущей версии.

    Возвращает новый словарь и исходную версию файла. Если версия файла выше
    текущей, данные возвращаются как есть: более новая версия приложения могла
    добавить ключи, которые мы обязаны сохранить.
    """
    version = detect_version(data)
    if version > CURRENT_SCHEMA_VERSION:
        logger.warning(
            "Файл настроек версии %s новее поддерживаемой %s, оставляю как есть",
            version,
            CURRENT_SCHEMA_VERSION,
        )
        return dict(data), version

    original = version
    result = dict(data)
    while version < CURRENT_SCHEMA_VERSION:
        migration = MIGRATIONS.get(version)
        if migration is None:
            raise RuntimeError(
                f"Нет миграции с версии {version} на {version + 1}. "
                "Добавьте её в MIGRATIONS."
            )
        result = migration(result)
        version += 1
        logger.info("Настройки мигрированы до версии %s", version)

    result["schema_version"] = CURRENT_SCHEMA_VERSION
    return result, original
