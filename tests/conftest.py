"""Общие настройки тестов.

Тесты обязаны работать с изолированным профилем: ни один из них не должен
трогать реальные настройки, историю или логи пользователя.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from voiceflow import paths


@pytest.fixture(autouse=True)
def isolated_home(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Уводит пользовательские данные во временный каталог на время теста."""
    home = tmp_path_factory.mktemp("voiceflow-home")
    monkeypatch.setenv(paths.HOME_ENV_VAR, str(home))
    return home
