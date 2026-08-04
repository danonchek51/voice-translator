"""Миграции файла настроек."""

from __future__ import annotations

import pytest

from voiceflow.core.settings import migrations
from voiceflow.core.settings.schema import CURRENT_SCHEMA_VERSION


def test_missing_version_is_zero() -> None:
    assert migrations.detect_version({}) == 0
    assert migrations.detect_version({"audio": {}}) == 0


def test_explicit_version_is_read() -> None:
    assert migrations.detect_version({"schema_version": 1}) == 1


def test_flat_prototype_keys_move_into_sections() -> None:
    legacy = {
        "wake_phrase": "пиши",
        "hotkey": "<ctrl>+<alt>+q",
        "auto_paste": False,
        "history_limit": 20,
        "audio": {"gain": 2.0},
    }

    migrated, original = migrations.migrate(legacy)

    assert original == 0
    assert migrated["schema_version"] == CURRENT_SCHEMA_VERSION
    assert migrated["activation"]["wake_phrase"] == "пиши"
    assert migrated["activation"]["hotkey"] == "<ctrl>+<alt>+q"
    assert migrated["output"]["auto_paste"] is False
    assert migrated["history"]["max_entries"] == 20
    # Уже существовавший раздел не затирается.
    assert migrated["audio"]["gain"] == 2.0
    # Плоские ключи убраны из корня.
    assert "wake_phrase" not in migrated


def test_existing_section_value_wins_over_flat_key() -> None:
    legacy = {
        "wake_phrase": "старое",
        "activation": {"wake_phrase": "новое"},
    }

    migrated, _ = migrations.migrate(legacy)

    assert migrated["activation"]["wake_phrase"] == "новое"


# --------------------------------------------------------------------------- #
# Версия 1 -> 2: выбор режима заменён галочками шагов
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (
            "raw",
            {"clean_enabled": False, "translate_enabled": False, "prompt_mode_enabled": False},
        ),
        (
            "clean",
            {"clean_enabled": True, "translate_enabled": False, "prompt_mode_enabled": False},
        ),
        (
            "translate",
            {"clean_enabled": True, "translate_enabled": True, "prompt_mode_enabled": False},
        ),
        (
            "prompt",
            {"clean_enabled": True, "translate_enabled": False, "prompt_mode_enabled": True},
        ),
    ],
)
def test_default_mode_becomes_step_flags(mode: str, expected: dict[str, bool]) -> None:
    data = {"schema_version": 1, "processing": {"default_mode": mode}}

    migrated, original = migrations.migrate(data)

    assert original == 1
    assert "default_mode" not in migrated["processing"]
    for key, value in expected.items():
        assert migrated["processing"][key] is value


def test_migration_keeps_other_processing_keys() -> None:
    data = {
        "schema_version": 1,
        "processing": {"default_mode": "clean", "use_llm": False, "guard_strict": False},
    }

    migrated, _ = migrations.migrate(data)

    assert migrated["processing"]["use_llm"] is False
    assert migrated["processing"]["guard_strict"] is False


def test_migration_survives_missing_processing_section() -> None:
    migrated, _ = migrations.migrate({"schema_version": 1, "audio": {"gain": 2.0}})

    assert migrated["schema_version"] == CURRENT_SCHEMA_VERSION
    assert migrated["audio"] == {"gain": 2.0}


def test_full_chain_from_prototype_to_current() -> None:
    """Файл нулевой версии должен подняться до текущей за один вызов."""
    legacy = {"wake_phrase": "пиши текст", "auto_paste": False}

    migrated, original = migrations.migrate(legacy)

    assert original == 0
    assert migrated["schema_version"] == CURRENT_SCHEMA_VERSION
    assert migrated["activation"]["wake_phrase"] == "пиши текст"


def test_current_version_is_not_touched() -> None:
    data = {"schema_version": CURRENT_SCHEMA_VERSION, "audio": {"gain": 1.5}}

    migrated, original = migrations.migrate(data)

    assert original == CURRENT_SCHEMA_VERSION
    assert migrated == data
    assert not migrations.needs_migration(data)


def test_newer_version_is_preserved_as_is() -> None:
    future = {"schema_version": CURRENT_SCHEMA_VERSION + 5, "brand_new": {"key": 1}}

    migrated, original = migrations.migrate(future)

    assert original == CURRENT_SCHEMA_VERSION + 5
    assert migrated["brand_new"] == {"key": 1}


def test_missing_migration_is_reported() -> None:
    original_chain = dict(migrations.MIGRATIONS)
    try:
        migrations.MIGRATIONS.clear()
        with pytest.raises(RuntimeError, match="Нет миграции"):
            migrations.migrate({"schema_version": 0})
    finally:
        migrations.MIGRATIONS.clear()
        migrations.MIGRATIONS.update(original_chain)
