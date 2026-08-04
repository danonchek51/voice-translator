"""Разрешение путей: обычный режим, portable и явный VOICEFLOW_HOME."""

from __future__ import annotations

from pathlib import Path

import pytest

from voiceflow import paths


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(paths.HOME_ENV_VAR, raising=False)


def test_forced_home_overrides_everything(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(paths.HOME_ENV_VAR, str(tmp_path))

    assert paths.user_data_root() == tmp_path
    assert paths.user_config_root() == tmp_path / "config"
    assert paths.settings_file() == tmp_path / "config" / "settings.toml"
    assert paths.history_db() == tmp_path / "data" / "history.db"
    assert paths.logs_dir() == tmp_path / "logs"
    assert paths.models_dir() == tmp_path / "models"


def test_bundle_root_equals_app_root_in_development() -> None:
    assert paths.bundle_root() == paths.app_root()
    assert paths.config_dir() == paths.app_root() / "config"


def test_frozen_build_reads_config_from_bundle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """PyInstaller 6 кладёт данные в _internal, а не рядом с exe."""
    exe_dir = tmp_path / "VoiceFlow"
    bundle = exe_dir / "_internal"
    bundle.mkdir(parents=True)
    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    monkeypatch.setattr(paths, "app_root", lambda: exe_dir)
    monkeypatch.setattr(paths.sys, "_MEIPASS", str(bundle), raising=False)

    assert paths.bundle_root() == bundle
    assert paths.config_dir() == bundle / "config"


def test_frozen_build_without_meipass_falls_back_to_app_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    monkeypatch.setattr(paths, "app_root", lambda: tmp_path)
    monkeypatch.delattr(paths.sys, "_MEIPASS", raising=False)

    assert paths.bundle_root() == tmp_path


def test_forced_home_disables_portable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app_root = tmp_path / "app"
    app_root.mkdir()
    (app_root / paths.PORTABLE_MARKER).write_text("", encoding="utf-8")
    monkeypatch.setattr(paths, "app_root", lambda: app_root)
    monkeypatch.setenv(paths.HOME_ENV_VAR, str(tmp_path / "home"))

    assert paths.is_portable() is False
    assert paths.user_data_root() == tmp_path / "home"


def test_portable_mode_keeps_everything_next_to_app(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app_root = tmp_path / "app"
    app_root.mkdir()
    (app_root / paths.PORTABLE_MARKER).write_text("", encoding="utf-8")
    monkeypatch.setattr(paths, "app_root", lambda: app_root)

    assert paths.is_portable() is True
    assert paths.user_data_root() == app_root / "userdata"
    assert paths.settings_file() == app_root / "userdata" / "config" / "settings.toml"
    assert paths.models_dir() == app_root / "userdata" / "models"
    # Заводская конфигурация в portable-режиме остаётся рядом с приложением.
    assert paths.config_dir() == app_root / "config"


def test_normal_mode_uses_profile(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    app_root = tmp_path / "app"
    app_root.mkdir()
    monkeypatch.setattr(paths, "app_root", lambda: app_root)

    assert paths.is_portable() is False
    # Точное расположение зависит от системы, но данные обязаны быть вне приложения.
    assert app_root not in paths.user_data_root().parents
    assert paths.user_data_root() != app_root


def test_ensure_user_dirs_creates_everything(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(paths.HOME_ENV_VAR, str(tmp_path))

    paths.ensure_user_dirs()

    for path in (
        paths.user_config_root(),
        paths.user_prompts_dir(),
        paths.data_dir(),
        paths.logs_dir(),
        paths.models_dir(),
        paths.cache_dir(),
    ):
        assert path.is_dir(), path


def test_describe_lists_all_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(paths.HOME_ENV_VAR, str(tmp_path))

    described = paths.describe()

    assert set(described) >= {"app_root", "config_dir", "settings_file", "history_db"}
    assert all(isinstance(value, str) for value in described.values())
