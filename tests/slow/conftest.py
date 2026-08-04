"""Медленные тесты работают с настоящим профилем пользователя.

Общая фикстура ``isolated_home`` уводит данные во временный каталог, но здесь
это лишает тесты доступа к загруженным моделям. Переопределяем её пустышкой:
каталог берётся тот, что реально настроен у разработчика.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from voiceflow import paths


@pytest.fixture(autouse=True)
def isolated_home() -> Path:
    """Ничего не подменяет: моделям нужен настоящий каталог."""
    return paths.user_data_root()
