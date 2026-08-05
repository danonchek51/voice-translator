"""Цепочка языковой модели: модель, сервер, путь в настройках.

Разрыв в любом звене приводит к одному и тому же незаметному последствию:
перевод и режим «Инструкция» молча выключаются, а в окно уходит текст после
очистки правилами. Поэтому каждое звено проверяется отдельно.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from voiceflow.core.models.catalog import load_catalog
from voiceflow.core.models.manager import ModelManager


@pytest.fixture
def manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModelManager:
    from voiceflow.core.models import manager as manager_module

    monkeypatch.setattr(manager_module.paths, "models_dir", lambda: tmp_path / "models")
    monkeypatch.setattr(
        manager_module.paths, "whisper_models_dir", lambda: tmp_path / "models" / "whisper"
    )
    return ModelManager(load_catalog())


# --------------------------------------------------------------------------- #
# Сервер модели
# --------------------------------------------------------------------------- #


def test_server_is_downloadable_not_manual() -> None:
    """Без сервера модель бесполезна, поэтому он не может ставиться руками."""
    spec = load_catalog().by_id("llama-server")

    assert spec is not None
    assert spec.kind == "zip", "сервер должен загружаться вместе с остальным"
    assert spec.url
    assert spec.size_bytes > 0


def test_server_lands_where_it_is_looked_for(manager: ModelManager) -> None:
    """Распаковка обязана попасть ровно туда, где сервер ищет приложение."""
    from voiceflow.core.llm.llama_server import executable_path

    spec = manager.catalog.by_id("llama-server")
    assert spec is not None
    from voiceflow.core.models import manager as manager_module

    monkey_runtime = manager_module.paths.models_dir() / "runtime" / "llama.cpp"

    assert spec.local_path() == monkey_runtime
    # Тот же путь, что и у клиента сервера, с поправкой на подменённый корень.
    assert executable_path().parent.name == "llama.cpp"
    assert executable_path().parent.parent.name == "runtime"


def test_server_counts_as_installed_when_unpacked(manager: ModelManager) -> None:
    spec = manager.catalog.by_id("llama-server")
    assert spec is not None
    folder = spec.local_path()
    folder.mkdir(parents=True)

    assert manager.is_installed(spec) is False

    (folder / "llama-server.exe").write_bytes(b"binary")
    assert manager.is_installed(spec) is True


def test_server_is_part_of_presets_with_llm() -> None:
    catalog = load_catalog()
    spec = catalog.by_id("llama-server")
    assert spec is not None

    assert "standard" in spec.presets
    assert "quality" in spec.presets
    assert "light" not in spec.presets, "лёгкий пресет работает без языковой модели"


# --------------------------------------------------------------------------- #
# Путь к модели
# --------------------------------------------------------------------------- #


def test_no_llm_path_before_download(manager: ModelManager) -> None:
    assert manager.installed_llm_path("standard") is None


def test_llm_path_found_after_download(manager: ModelManager) -> None:
    spec = manager.catalog.by_id("qwen3-4b")
    assert spec is not None
    spec.local_path().parent.mkdir(parents=True, exist_ok=True)
    spec.local_path().write_bytes(b"gguf")

    found = manager.installed_llm_path("standard")

    assert found == spec.local_path()


def test_llm_path_ignores_other_presets(manager: ModelManager) -> None:
    """Модель качества не должна подставляться стандартному пресету."""
    spec = manager.catalog.by_id("qwen3-8b")
    assert spec is not None
    spec.local_path().parent.mkdir(parents=True, exist_ok=True)
    spec.local_path().write_bytes(b"gguf")

    assert manager.installed_llm_path("standard") is None
    assert manager.installed_llm_path("quality") == spec.local_path()


def test_llm_ready_requires_both_model_and_server(manager: ModelManager) -> None:
    model = manager.catalog.by_id("qwen3-4b")
    server = manager.catalog.by_id("llama-server")
    assert model is not None and server is not None

    model.local_path().parent.mkdir(parents=True, exist_ok=True)
    model.local_path().write_bytes(b"gguf")
    assert manager.is_llm_ready("standard") is False, "без сервера модель не работает"

    server.local_path().mkdir(parents=True, exist_ok=True)
    (server.local_path() / "llama-server.exe").write_bytes(b"binary")
    assert manager.is_llm_ready("standard") is True


def test_light_preset_does_not_promise_llm(manager: ModelManager) -> None:
    assert manager.installed_llm_path("light") is None
    assert manager.is_llm_ready("light") is False
