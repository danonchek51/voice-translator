"""Экспорт и импорт настроек."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from voiceflow import paths
from voiceflow.core.settings.schema import CURRENT_SCHEMA_VERSION
from voiceflow.core.settings.transfer import (
    BUNDLE_FORMAT,
    TransferError,
    export_settings,
    import_settings,
    inspect_bundle,
)


@pytest.fixture
def profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Пустой профиль пользователя в отдельной папке."""
    home = tmp_path / "home"
    monkeypatch.setenv(paths.HOME_ENV_VAR, str(home))
    paths.ensure_user_dirs()
    return home


def _fill_profile() -> None:
    paths.settings_file().write_text(
        'schema_version = 1\n\n[system]\nlog_level = "DEBUG"\n', encoding="utf-8"
    )
    paths.glossary_file().write_text(
        '[replacements]\n"курсор" = "Cursor"\n', encoding="utf-8"
    )
    (paths.user_prompts_dir() / "clean.ru.md").write_text(
        "---\nid: clean\ntitle: Моя очистка\n---\nПравь текст.\n", encoding="utf-8"
    )


# --------------------------------------------------------------------------- #
# Экспорт
# --------------------------------------------------------------------------- #


def test_export_packs_user_files(profile: Path, tmp_path: Path) -> None:
    _fill_profile()
    archive = tmp_path / "bundle.zip"

    result = export_settings(archive)

    assert archive.is_file()
    assert "settings.toml" in result.items
    assert "glossary.toml" in result.items
    assert "prompts/clean.ru.md" in result.items
    with zipfile.ZipFile(archive) as bundle:
        assert "manifest.toml" in bundle.namelist()


def test_export_skips_history_by_default(profile: Path, tmp_path: Path) -> None:
    _fill_profile()
    paths.history_db().write_bytes(b"fake-sqlite")
    archive = tmp_path / "bundle.zip"

    export_settings(archive)

    assert not inspect_bundle(archive).has_history


def test_export_includes_history_on_request(profile: Path, tmp_path: Path) -> None:
    _fill_profile()
    paths.history_db().write_bytes(b"fake-sqlite")
    archive = tmp_path / "bundle.zip"

    export_settings(archive, include_history=True)

    assert inspect_bundle(archive).has_history


def test_export_never_packs_models(profile: Path, tmp_path: Path) -> None:
    _fill_profile()
    model = paths.models_dir() / "asr" / "big.onnx"
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_bytes(b"x" * 1024)
    archive = tmp_path / "bundle.zip"

    export_settings(archive)

    with zipfile.ZipFile(archive) as bundle:
        assert not any("onnx" in name for name in bundle.namelist())


def test_export_without_settings_leaves_note(profile: Path, tmp_path: Path) -> None:
    archive = tmp_path / "bundle.zip"

    result = export_settings(archive)

    assert result.notes


# --------------------------------------------------------------------------- #
# Осмотр архива
# --------------------------------------------------------------------------- #


def test_inspect_reports_contents(profile: Path, tmp_path: Path) -> None:
    _fill_profile()
    archive = tmp_path / "bundle.zip"
    export_settings(archive)

    info = inspect_bundle(archive)

    assert info.format == BUNDLE_FORMAT
    assert info.is_supported
    assert info.has_settings
    assert info.prompts == ("clean.ru.md",)
    assert "настройки" in info.describe()


def test_inspect_rejects_foreign_zip(tmp_path: Path) -> None:
    archive = tmp_path / "foreign.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("readme.txt", "чужой архив")

    with pytest.raises(TransferError):
        inspect_bundle(archive)


def test_inspect_rejects_broken_file(tmp_path: Path) -> None:
    archive = tmp_path / "broken.zip"
    archive.write_bytes(b"not a zip at all")

    with pytest.raises(TransferError):
        inspect_bundle(archive)


def test_inspect_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(TransferError):
        inspect_bundle(tmp_path / "нет-такого.zip")


# --------------------------------------------------------------------------- #
# Импорт
# --------------------------------------------------------------------------- #


def test_import_restores_files(profile: Path, tmp_path: Path) -> None:
    _fill_profile()
    archive = tmp_path / "bundle.zip"
    export_settings(archive)

    # Портим профиль и восстанавливаем его из архива.
    paths.settings_file().write_text("сломано", encoding="utf-8")
    (paths.user_prompts_dir() / "clean.ru.md").unlink()

    result = import_settings(archive)

    assert "DEBUG" in paths.settings_file().read_text(encoding="utf-8")
    assert (paths.user_prompts_dir() / "clean.ru.md").is_file()
    assert "prompts/clean.ru.md" in result.items


def test_import_is_read_by_settings_store(profile: Path, tmp_path: Path) -> None:
    """Архив должен приводить приложение к перенесённым настройкам."""
    from voiceflow.core.settings.store import SettingsStore

    _fill_profile()
    archive = tmp_path / "bundle.zip"
    export_settings(archive)
    paths.settings_file().unlink()

    import_settings(archive)
    settings = SettingsStore().load()

    assert settings.system.log_level == "DEBUG"


def test_import_skips_history_by_default(profile: Path, tmp_path: Path) -> None:
    _fill_profile()
    paths.history_db().write_bytes(b"fake-sqlite")
    archive = tmp_path / "bundle.zip"
    export_settings(archive, include_history=True)
    paths.history_db().unlink()

    result = import_settings(archive)

    assert not paths.history_db().exists()
    assert result.notes


def test_import_restores_history_on_request(profile: Path, tmp_path: Path) -> None:
    _fill_profile()
    paths.history_db().write_bytes(b"fake-sqlite")
    archive = tmp_path / "bundle.zip"
    export_settings(archive, include_history=True)
    paths.history_db().unlink()

    import_settings(archive, include_history=True)

    assert paths.history_db().read_bytes() == b"fake-sqlite"


def test_import_warns_about_newer_schema(profile: Path, tmp_path: Path) -> None:
    _fill_profile()
    archive = tmp_path / "bundle.zip"
    export_settings(archive)

    # Подменяем манифест на версию из будущего.
    rebuilt = tmp_path / "future.zip"
    current = f"schema_version = {CURRENT_SCHEMA_VERSION}".encode()
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(rebuilt, "w") as target:
        for name in source.namelist():
            data = source.read(name)
            if name == "manifest.toml":
                data = data.replace(current, b"schema_version = 99")
            target.writestr(name, data)

    result = import_settings(rebuilt)

    assert any("более новой версией" in note for note in result.notes)
