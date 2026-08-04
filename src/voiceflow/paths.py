"""Единственное место в проекте, где вычисляются пути к данным.

Три режима работы:

* обычный — пользовательские данные лежат в профиле операционной системы;
* portable — рядом с приложением есть файл ``portable.txt``, все данные лежат
  в подпапках каталога приложения;
* тестовый — переменная окружения ``VOICEFLOW_HOME`` задаёт корень явно.

Модуль не импортирует ничего платформозависимого: разветвление идёт по
``sys.platform``, а не по наличию Windows-библиотек.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "VoiceFlow"

#: Переменная окружения, полностью переопределяющая корень пользовательских данных.
HOME_ENV_VAR = "VOICEFLOW_HOME"

#: Файл-маркер portable-режима рядом с исполняемым файлом.
PORTABLE_MARKER = "portable.txt"


def is_frozen() -> bool:
    """Приложение запущено из сборки PyInstaller."""
    return getattr(sys, "frozen", False)


def app_root() -> Path:
    """Каталог приложения: рядом с ним живут ``portable.txt`` и данные.

    В собранном виде это папка с исполняемым файлом, в разработке — корень
    репозитория.
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    # src/voiceflow/paths.py -> src/voiceflow -> src -> корень
    return Path(__file__).resolve().parents[2]


def bundle_root() -> Path:
    """Каталог с упакованными данными.

    PyInstaller, начиная с шестой версии, кладёт данные не рядом с exe,
    а в подпапку ``_internal`` и сообщает её путь через ``sys._MEIPASS``.
    Полагаться на расположение рядом с exe нельзя: сборка перестанет
    находить заводские настройки и инструкции.
    """
    if is_frozen():
        bundled = getattr(sys, "_MEIPASS", None)
        if bundled:
            return Path(str(bundled))
    return app_root()


def config_dir() -> Path:
    """Заводские настройки, промпты и словари. Только для чтения."""
    return bundle_root() / "config"


def is_portable() -> bool:
    """Portable-режим включён файлом-маркером и отключён явным ``VOICEFLOW_HOME``."""
    if os.environ.get(HOME_ENV_VAR):
        return False
    return (app_root() / PORTABLE_MARKER).exists()


def _os_config_root() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / APP_NAME
        return Path.home() / "AppData" / "Roaming" / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return (Path(xdg) if xdg else Path.home() / ".config") / APP_NAME


def _os_data_root() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / APP_NAME
        return Path.home() / "AppData" / "Local" / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    xdg = os.environ.get("XDG_DATA_HOME")
    return (Path(xdg) if xdg else Path.home() / ".local" / "share") / APP_NAME


def _forced_home() -> Path | None:
    raw = os.environ.get(HOME_ENV_VAR)
    return Path(raw) if raw else None


def user_config_root() -> Path:
    """Корень пользовательских настроек: настройки, промпты, глоссарий."""
    forced = _forced_home()
    if forced is not None:
        return forced / "config"
    if is_portable():
        return app_root() / "userdata" / "config"
    return _os_config_root()


def user_data_root() -> Path:
    """Корень изменяемых данных: история, логи, модели, кэш."""
    forced = _forced_home()
    if forced is not None:
        return forced
    if is_portable():
        return app_root() / "userdata"
    return _os_data_root()


def settings_file() -> Path:
    return user_config_root() / "settings.toml"


def user_prompts_dir() -> Path:
    """Изменённые пользователем инструкции. Неизменённые сюда не копируются."""
    return user_config_root() / "prompts"


def glossary_file() -> Path:
    return user_config_root() / "glossary.toml"


def data_dir() -> Path:
    return user_data_root() / "data"


def history_db() -> Path:
    return data_dir() / "history.db"


def logs_dir() -> Path:
    return user_data_root() / "logs"


def models_dir() -> Path:
    return user_data_root() / "models"


def runtime_dir() -> Path:
    """Внешние исполняемые файлы: llama-server и сопутствующие библиотеки."""
    return models_dir() / "runtime"


def hf_cache_dir() -> Path:
    """Кэш Hugging Face. Держим внутри своего каталога моделей.

    Иначе гигабайты расходятся по профилю пользователя и не переносятся
    вместе с portable-версией.
    """
    return models_dir() / "hf"


def whisper_models_dir() -> Path:
    return models_dir() / "whisper"


def cache_dir() -> Path:
    return user_data_root() / "cache"


def ensure_user_dirs() -> None:
    """Создаёт каталоги пользовательских данных. Вызывается один раз при старте."""
    for path in (
        user_config_root(),
        user_prompts_dir(),
        data_dir(),
        logs_dir(),
        models_dir(),
        cache_dir(),
    ):
        path.mkdir(parents=True, exist_ok=True)


def describe() -> dict[str, str]:
    """Сводка путей для вкладки диагностики и для отчётов об ошибках."""
    return {
        "app_root": str(app_root()),
        "bundle_root": str(bundle_root()),
        "config_dir": str(config_dir()),
        "portable": str(is_portable()),
        "settings_file": str(settings_file()),
        "user_prompts_dir": str(user_prompts_dir()),
        "glossary_file": str(glossary_file()),
        "history_db": str(history_db()),
        "logs_dir": str(logs_dir()),
        "models_dir": str(models_dir()),
        "cache_dir": str(cache_dir()),
    }
