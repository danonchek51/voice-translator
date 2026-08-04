"""Перенос настроек между компьютерами.

В архив попадает только то, что пользователь настроил своими руками:
файл настроек, изменённые инструкции и словарь замен. Модели не включаются
никогда — они весят десятки гигабайт и загружаются мастером заново.
История добавляется только по явному запросу.

Формат архива описан файлом ``manifest.toml``: он позволяет отличить чужой
zip от нашего и понять, какой версией схемы он создан.
"""

from __future__ import annotations

import logging
import tomllib
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import tomli_w

from voiceflow import __version__, paths
from voiceflow.core.settings.schema import CURRENT_SCHEMA_VERSION

logger = logging.getLogger(__name__)

MANIFEST_NAME = "manifest.toml"
SETTINGS_NAME = "settings.toml"
GLOSSARY_NAME = "glossary.toml"
PROMPTS_DIR = "prompts"
HISTORY_NAME = "history.db"

#: Метка формата. Меняется, если состав архива станет несовместимым.
BUNDLE_FORMAT = 1


class TransferError(RuntimeError):
    """Архив не наш, повреждён или не читается."""


@dataclass(frozen=True, slots=True)
class BundleInfo:
    """Что лежит в архиве. Показывается пользователю до импорта."""

    format: int
    schema_version: int
    app_version: str
    created_at: str
    has_settings: bool = False
    has_glossary: bool = False
    has_history: bool = False
    prompts: tuple[str, ...] = ()

    @property
    def is_supported(self) -> bool:
        return self.format == BUNDLE_FORMAT

    def describe(self) -> str:
        parts: list[str] = []
        if self.has_settings:
            parts.append("настройки")
        if self.has_glossary:
            parts.append("словарь замен")
        if self.prompts:
            parts.append(f"инструкции ({len(self.prompts)})")
        if self.has_history:
            parts.append("история")
        return ", ".join(parts) or "пусто"


@dataclass(slots=True)
class TransferResult:
    """Итог экспорта или импорта."""

    archive: Path
    items: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def export_settings(archive: Path, *, include_history: bool = False) -> TransferResult:
    """Складывает пользовательские файлы в zip."""
    archive = Path(archive)
    archive.parent.mkdir(parents=True, exist_ok=True)

    result = TransferResult(archive=archive)
    manifest: dict[str, object] = {
        "format": BUNDLE_FORMAT,
        "schema_version": CURRENT_SCHEMA_VERSION,
        "app_version": __version__,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }

    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        settings_file = paths.settings_file()
        if settings_file.is_file():
            bundle.write(settings_file, SETTINGS_NAME)
            result.items.append(SETTINGS_NAME)
        else:
            result.notes.append("файл настроек не найден: сохранены только заводские значения")

        glossary = paths.glossary_file()
        if glossary.is_file():
            bundle.write(glossary, GLOSSARY_NAME)
            result.items.append(GLOSSARY_NAME)

        prompts_dir = paths.user_prompts_dir()
        if prompts_dir.is_dir():
            for prompt in sorted(prompts_dir.glob("*.md")):
                bundle.write(prompt, f"{PROMPTS_DIR}/{prompt.name}")
                result.items.append(f"{PROMPTS_DIR}/{prompt.name}")

        if include_history:
            history = paths.history_db()
            if history.is_file():
                bundle.write(history, HISTORY_NAME)
                result.items.append(HISTORY_NAME)
            else:
                result.notes.append("история пуста, в архив не добавлена")

        bundle.writestr(MANIFEST_NAME, tomli_w.dumps(manifest))

    logger.info("Настройки экспортированы в %s (%s)", archive, ", ".join(result.items))
    return result


def inspect_bundle(archive: Path) -> BundleInfo:
    """Читает манифест, ничего не распаковывая."""
    archive = Path(archive)
    if not archive.is_file():
        raise TransferError(f"Файл не найден: {archive}")

    try:
        with zipfile.ZipFile(archive) as bundle:
            names = set(bundle.namelist())
            if MANIFEST_NAME not in names:
                raise TransferError(
                    "Это не архив настроек VoiceFlow: внутри нет manifest.toml"
                )
            manifest = tomllib.loads(bundle.read(MANIFEST_NAME).decode("utf-8"))
    except zipfile.BadZipFile as exc:
        raise TransferError(f"Архив повреждён: {exc}") from exc
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise TransferError(f"Манифест архива не читается: {exc}") from exc

    return BundleInfo(
        format=int(manifest.get("format", 0)),
        schema_version=int(manifest.get("schema_version", 0)),
        app_version=str(manifest.get("app_version", "")),
        created_at=str(manifest.get("created_at", "")),
        has_settings=SETTINGS_NAME in names,
        has_glossary=GLOSSARY_NAME in names,
        has_history=HISTORY_NAME in names,
        prompts=tuple(
            sorted(
                Path(name).name
                for name in names
                if name.startswith(f"{PROMPTS_DIR}/") and name.endswith(".md")
            )
        ),
    )


def import_settings(archive: Path, *, include_history: bool = False) -> TransferResult:
    """Раскладывает содержимое архива по профилю пользователя.

    Миграция схемы не выполняется здесь: файл настроек читает
    :class:`SettingsStore`, он же поднимет старую версию до текущей.
    """
    info = inspect_bundle(archive)
    if not info.is_supported:
        raise TransferError(
            f"Архив создан несовместимой версией (формат {info.format}, "
            f"поддерживается {BUNDLE_FORMAT})"
        )

    result = TransferResult(archive=Path(archive))
    if info.schema_version > CURRENT_SCHEMA_VERSION:
        result.notes.append(
            f"архив создан более новой версией приложения (схема "
            f"{info.schema_version} против {CURRENT_SCHEMA_VERSION}); "
            "незнакомые настройки будут сохранены, но не применены"
        )

    paths.ensure_user_dirs()
    with zipfile.ZipFile(archive) as bundle:
        if info.has_settings:
            paths.settings_file().write_bytes(bundle.read(SETTINGS_NAME))
            result.items.append(SETTINGS_NAME)

        if info.has_glossary:
            paths.glossary_file().write_bytes(bundle.read(GLOSSARY_NAME))
            result.items.append(GLOSSARY_NAME)

        for name in info.prompts:
            target = paths.user_prompts_dir() / name
            target.write_bytes(bundle.read(f"{PROMPTS_DIR}/{name}"))
            result.items.append(f"{PROMPTS_DIR}/{name}")

        if include_history and info.has_history:
            paths.history_db().write_bytes(bundle.read(HISTORY_NAME))
            result.items.append(HISTORY_NAME)
        elif info.has_history and not include_history:
            result.notes.append("история в архиве есть, но импорт её не запрашивал")

    logger.info("Импортировано из %s: %s", archive, ", ".join(result.items) or "пусто")
    return result
