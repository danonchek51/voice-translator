"""Загрузка, сохранение и сброс настроек.

Порядок наложения при загрузке:

1. значения по умолчанию из dataclass — приложение обязано стартовать даже без
   каталога ``config``;
2. заводской файл ``config/default_settings.toml``, если он есть;
3. пользовательский файл, приведённый к текущей версии схемы.

При сохранении в пользовательский файл пишутся только отличия от заводских
значений. Поэтому «сбросить раздел» — это удаление ключей раздела, а не запись
умолчаний.
"""

from __future__ import annotations

import logging
import shutil
import threading
import tomllib
from pathlib import Path
from typing import Any

import tomli_w

from voiceflow import paths
from voiceflow.core.settings import migrations
from voiceflow.core.settings.schema import (
    CURRENT_SCHEMA_VERSION,
    SECTION_NAMES,
    Settings,
    deep_merge,
    diff_from_defaults,
    from_dict,
    to_dict,
    validate,
)

logger = logging.getLogger(__name__)


class SettingsStore:
    """Владелец текущих настроек. Единственная точка записи файла."""

    def __init__(
        self,
        user_file: Path | None = None,
        factory_file: Path | None = None,
    ) -> None:
        self._user_file = user_file or paths.settings_file()
        self._factory_file = factory_file or (paths.config_dir() / "default_settings.toml")
        self._lock = threading.RLock()
        self._settings = Settings()
        self._factory_dict: dict[str, Any] = {}
        #: Сырой пользовательский словарь целиком, включая незнакомые ключи.
        self._user_raw: dict[str, Any] = {}
        self._notes: list[str] = []
        self._loaded = False

    # ------------------------------------------------------------------ #
    # Свойства
    # ------------------------------------------------------------------ #

    @property
    def settings(self) -> Settings:
        with self._lock:
            if not self._loaded:
                self.load()
            return self._settings

    @property
    def notes(self) -> list[str]:
        """Замечания последней загрузки: исправленные значения, битый файл."""
        with self._lock:
            return list(self._notes)

    @property
    def user_file(self) -> Path:
        return self._user_file

    # ------------------------------------------------------------------ #
    # Загрузка
    # ------------------------------------------------------------------ #

    def load(self) -> Settings:
        """Читает файлы и собирает настройки. Никогда не бросает исключение."""
        with self._lock:
            notes: list[str] = []

            self._factory_dict = self._read_toml(self._factory_file, notes, "заводской файл")
            user_raw = self._read_toml(self._user_file, notes, "файл настроек")

            if user_raw and migrations.needs_migration(user_raw):
                migrated, original_version = migrations.migrate(user_raw)
                self._backup(original_version, notes)
                user_raw = migrated
                self._user_raw = migrated
                self._write_raw(user_raw, notes)
            else:
                self._user_raw = user_raw

            merged = deep_merge(to_dict(Settings()), self._factory_dict)
            merged = deep_merge(merged, user_raw)

            settings = from_dict(merged)
            settings.schema_version = CURRENT_SCHEMA_VERSION
            notes.extend(validate(settings))

            self._settings = settings
            self._notes = notes
            self._loaded = True

            for note in notes:
                logger.warning("Настройки: %s", note)
            return settings

    def _read_toml(self, path: Path, notes: list[str], label: str) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            with path.open("rb") as handle:
                return tomllib.load(handle)
        except (tomllib.TOMLDecodeError, OSError) as exc:
            notes.append(f"{label} повреждён ({exc}); использую заводские значения")
            self._quarantine(path, notes)
            return {}

    def _quarantine(self, path: Path, notes: list[str]) -> None:
        """Отодвигает нечитаемый файл, чтобы он не мешал следующему запуску."""
        broken = path.with_suffix(path.suffix + ".broken")
        try:
            shutil.move(str(path), str(broken))
            notes.append(f"повреждённый файл сохранён как {broken.name}")
        except OSError:
            logger.exception("Не удалось отодвинуть повреждённый файл %s", path)

    def _backup(self, version: int, notes: list[str]) -> None:
        backup = self._user_file.with_suffix(f".toml.bak.v{version}")
        try:
            shutil.copy2(self._user_file, backup)
            notes.append(f"перед миграцией создана копия {backup.name}")
        except OSError:
            logger.exception("Не удалось создать резервную копию настроек")

    # ------------------------------------------------------------------ #
    # Сохранение
    # ------------------------------------------------------------------ #

    def save(self, settings: Settings | None = None) -> list[str]:
        """Сохраняет отличия от заводских значений. Возвращает замечания."""
        with self._lock:
            if settings is not None:
                self._settings = settings
            notes = validate(self._settings)

            factory_defaults = from_dict(deep_merge(to_dict(Settings()), self._factory_dict))
            sparse = diff_from_defaults(self._settings, factory_defaults)

            # Незнакомые ключи из пользовательского файла сохраняются как есть.
            preserved = self._unknown_keys(self._user_raw)
            payload = deep_merge(preserved, sparse)

            self._write_raw(payload, notes)
            self._user_raw = payload
            self._notes = notes
            return notes

    @staticmethod
    def _unknown_keys(raw: dict[str, Any]) -> dict[str, Any]:
        """Ключи пользовательского файла, которых нет в текущей схеме."""
        known_sections = set(SECTION_NAMES)
        template = to_dict(Settings())
        result: dict[str, Any] = {}
        for key, value in raw.items():
            if key == "schema_version":
                continue
            if key not in known_sections:
                result[key] = value
                continue
            if not isinstance(value, dict):
                continue
            known_fields = set(template[key])
            extra = {k: v for k, v in value.items() if k not in known_fields}
            if extra:
                result[key] = extra
        return result

    def _write_raw(self, payload: dict[str, Any], notes: list[str]) -> None:
        """Атомарная запись: сначала временный файл, затем замена."""
        try:
            self._user_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._user_file.with_suffix(".toml.tmp")
            with tmp.open("wb") as handle:
                tomli_w.dump(_drop_none(payload), handle)
            tmp.replace(self._user_file)
        except OSError as exc:
            notes.append(f"не удалось сохранить настройки: {exc}")
            logger.exception("Ошибка записи настроек в %s", self._user_file)

    # ------------------------------------------------------------------ #
    # Сброс
    # ------------------------------------------------------------------ #

    def reset_section(self, section: str) -> list[str]:
        """Возвращает раздел к заводским значениям."""
        if section not in SECTION_NAMES:
            raise ValueError(f"Неизвестный раздел настроек: {section}")
        with self._lock:
            factory_defaults = from_dict(deep_merge(to_dict(Settings()), self._factory_dict))
            setattr(self._settings, section, getattr(factory_defaults, section))
            self._user_raw.pop(section, None)
            return self.save()

    def reset_all(self) -> list[str]:
        """Возвращает все настройки к заводским значениям."""
        with self._lock:
            factory_defaults = from_dict(deep_merge(to_dict(Settings()), self._factory_dict))
            factory_defaults.schema_version = CURRENT_SCHEMA_VERSION
            self._settings = factory_defaults
            self._user_raw = {}
            return self.save()


def _drop_none(value: Any) -> Any:
    """TOML не умеет ``None``; отсутствие ключа и означает «заводское значение»."""
    if isinstance(value, dict):
        return {k: _drop_none(v) for k, v in value.items() if v is not None}
    return value
