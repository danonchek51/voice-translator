"""Загрузка, сохранение и сброс настроек."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from voiceflow.core.settings.schema import CURRENT_SCHEMA_VERSION, Settings, validate
from voiceflow.core.settings.store import SettingsStore


@pytest.fixture
def store(tmp_path: Path) -> SettingsStore:
    return SettingsStore(
        user_file=tmp_path / "settings.toml",
        factory_file=tmp_path / "default_settings.toml",
    )


def read_toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def test_loads_dataclass_defaults_without_any_file(store: SettingsStore) -> None:
    settings = store.load()

    assert settings.schema_version == CURRENT_SCHEMA_VERSION
    assert settings.activation.wake_enabled is False
    assert settings.history.max_entries == 50
    assert store.notes == []


def test_factory_file_overrides_code_defaults(tmp_path: Path) -> None:
    factory = tmp_path / "default_settings.toml"
    factory.write_text(
        'schema_version = 2\n[history]\nmax_entries = 20\n', encoding="utf-8"
    )
    store = SettingsStore(user_file=tmp_path / "settings.toml", factory_file=factory)

    settings = store.load()

    assert settings.history.max_entries == 20


def test_user_file_overrides_factory(tmp_path: Path) -> None:
    factory = tmp_path / "default_settings.toml"
    factory.write_text('schema_version = 2\n[history]\nmax_entries = 20\n', encoding="utf-8")
    user = tmp_path / "settings.toml"
    user.write_text('schema_version = 2\n[history]\nmax_entries = 100\n', encoding="utf-8")
    store = SettingsStore(user_file=user, factory_file=factory)

    assert store.load().history.max_entries == 100


def test_save_writes_only_differences(store: SettingsStore) -> None:
    settings = store.load()
    settings.overlay.opacity = 55

    store.save(settings)

    written = read_toml(store.user_file)
    assert written == {"schema_version": CURRENT_SCHEMA_VERSION, "overlay": {"opacity": 55}}


def test_none_values_are_not_written(store: SettingsStore) -> None:
    settings = store.load()
    settings.overlay.x = None
    settings.overlay.y = 42

    store.save(settings)

    written = read_toml(store.user_file)
    assert written["overlay"] == {"y": 42}


def test_reset_section_removes_its_keys(store: SettingsStore) -> None:
    settings = store.load()
    settings.overlay.opacity = 40
    settings.history.max_entries = 10
    store.save(settings)

    store.reset_section("overlay")

    written = read_toml(store.user_file)
    assert "overlay" not in written
    assert written["history"] == {"max_entries": 10}
    assert store.settings.overlay.opacity == Settings().overlay.opacity


def test_reset_all_empties_user_file(store: SettingsStore) -> None:
    settings = store.load()
    settings.overlay.opacity = 40
    settings.history.max_entries = 10
    store.save(settings)

    store.reset_all()

    assert read_toml(store.user_file) == {"schema_version": CURRENT_SCHEMA_VERSION}


def test_reset_unknown_section_is_rejected(store: SettingsStore) -> None:
    store.load()
    with pytest.raises(ValueError, match="Неизвестный раздел"):
        store.reset_section("нет_такого")


def test_unknown_keys_survive_save(tmp_path: Path) -> None:
    """Откат на предыдущую версию приложения не должен терять настройки."""
    user = tmp_path / "settings.toml"
    user.write_text(
        "schema_version = 2\n"
        "[future_section]\n"
        'flag = "оставить"\n'
        "[overlay]\n"
        "opacity = 70\n"
        "unknown_overlay_key = 5\n",
        encoding="utf-8",
    )
    store = SettingsStore(user_file=user, factory_file=tmp_path / "default_settings.toml")

    settings = store.load()
    settings.overlay.opacity = 80
    store.save(settings)

    written = read_toml(user)
    assert written["future_section"] == {"flag": "оставить"}
    assert written["overlay"]["unknown_overlay_key"] == 5
    assert written["overlay"]["opacity"] == 80


def test_migration_creates_backup_and_rewrites_file(tmp_path: Path) -> None:
    user = tmp_path / "settings.toml"
    user.write_text('wake_phrase = "пиши"\nauto_paste = false\n', encoding="utf-8")
    store = SettingsStore(user_file=user, factory_file=tmp_path / "default_settings.toml")

    settings = store.load()

    assert settings.activation.wake_phrase == "пиши"
    assert settings.output.auto_paste is False
    assert (tmp_path / "settings.toml.bak.v0").exists()
    assert read_toml(user)["schema_version"] == CURRENT_SCHEMA_VERSION
    assert any("копия" in note for note in store.notes)


def test_broken_file_is_quarantined_and_defaults_used(tmp_path: Path) -> None:
    user = tmp_path / "settings.toml"
    user.write_text("это [не TOML\n", encoding="utf-8")
    store = SettingsStore(user_file=user, factory_file=tmp_path / "default_settings.toml")

    settings = store.load()

    assert settings.history.max_entries == Settings().history.max_entries
    assert (tmp_path / "settings.toml.broken").exists()
    assert any("повреждён" in note for note in store.notes)


def test_invalid_values_are_repaired_with_notes(tmp_path: Path) -> None:
    user = tmp_path / "settings.toml"
    user.write_text(
        "schema_version = 2\n"
        "[activation]\n"
        'stop_mode = "телепатия"\n'
        "sensitivity = 99\n"
        "[history]\n"
        "max_entries = 37\n",
        encoding="utf-8",
    )
    store = SettingsStore(user_file=user, factory_file=tmp_path / "default_settings.toml")

    settings = store.load()

    assert settings.activation.stop_mode == Settings().activation.stop_mode
    assert settings.activation.sensitivity == 10
    assert settings.history.max_entries == 50
    assert len(store.notes) == 3


def test_wrong_types_fall_back_to_defaults(tmp_path: Path) -> None:
    user = tmp_path / "settings.toml"
    user.write_text(
        'schema_version = 2\n[output]\nauto_paste = "да"\npaste_delay_ms = "быстро"\n',
        encoding="utf-8",
    )
    store = SettingsStore(user_file=user, factory_file=tmp_path / "default_settings.toml")

    settings = store.load()

    assert settings.output.auto_paste is Settings().output.auto_paste
    assert settings.output.paste_delay_ms == Settings().output.paste_delay_ms


def test_validate_clamps_and_reports() -> None:
    settings = Settings()
    settings.overlay.opacity = 5
    settings.overlay.scale = 500
    settings.activation.wake_phrase = "   "

    notes = validate(settings)

    assert settings.overlay.opacity == 30
    assert settings.overlay.scale == 150
    assert settings.activation.wake_phrase == Settings().activation.wake_phrase
    assert len(notes) == 3


def test_repository_factory_file_is_valid() -> None:
    """Заводской TOML из репозитория должен читаться без единого замечания."""
    from voiceflow import paths

    store = SettingsStore(
        user_file=Path("нет-такого-файла.toml"),
        factory_file=paths.config_dir() / "default_settings.toml",
    )

    store.load()

    assert store.notes == []
