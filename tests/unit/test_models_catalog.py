"""Реестр и менеджер моделей."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from voiceflow.core.models.catalog import load_catalog
from voiceflow.core.models.manager import ModelManager


def test_load_bundled_catalog() -> None:
    catalog = load_catalog()
    assert catalog.by_id("silero-vad") is not None
    assert catalog.total_size("light") > 0
    light = {m.id for m in catalog.for_preset("light")}
    assert "silero-vad" in light
    assert "gigaam-ctc" in light


def test_verify_sha256(tmp_path: Path) -> None:
    file = tmp_path / "model.bin"
    content = b"voiceflow-model"
    file.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    assert ModelManager.verify_sha256(file, digest)
    assert not ModelManager.verify_sha256(file, "0" * 64)


def test_import_local(tmp_path: Path, monkeypatch) -> None:
    from voiceflow.core.models import manager as manager_module

    monkeypatch.setattr(manager_module.paths, "models_dir", lambda: tmp_path / "models")
    catalog = load_catalog()
    manager = ModelManager(catalog)
    source = tmp_path / "silero_vad.onnx"
    source.write_bytes(b"fake-onnx")
    target = manager.import_local("silero-vad", source)
    assert target.is_file()
    status = manager.status("silero-vad")
    assert status is not None and status.installed


# --------------------------------------------------------------------------- #
# План загрузки
# --------------------------------------------------------------------------- #


def _manager_on(tmp_path: Path, monkeypatch) -> ModelManager:
    from voiceflow.core.models import manager as manager_module

    monkeypatch.setattr(manager_module.paths, "models_dir", lambda: tmp_path / "models")
    return ModelManager(load_catalog())


def test_plan_on_empty_machine(tmp_path: Path, monkeypatch) -> None:
    manager = _manager_on(tmp_path, monkeypatch)
    plan = manager.download_plan("light")

    assert plan.installed == ()
    assert plan.missing
    assert plan.total_bytes > 0
    assert not plan.is_complete
    # В лёгком пресете нет моделей, требующих ручной установки.
    assert plan.manual == ()


def test_plan_separates_models_without_url(tmp_path: Path, monkeypatch) -> None:
    manager = _manager_on(tmp_path, monkeypatch)
    plan = manager.download_plan("standard")

    manual_ids = {spec.id for spec in plan.manual}
    missing_ids = {spec.id for spec in plan.missing}
    assert "llama-server-cuda" in manual_ids
    assert "llama-server-cuda" not in missing_ids
    # Ручная установка не должна попадать в объём загрузки.
    assert all(spec.url for spec in plan.missing)


def test_plan_counts_installed(tmp_path: Path, monkeypatch) -> None:
    manager = _manager_on(tmp_path, monkeypatch)
    source = tmp_path / "silero_vad.onnx"
    source.write_bytes(b"fake-onnx")
    manager.import_local("silero-vad", source)

    plan = manager.download_plan("light")
    assert {spec.id for spec in plan.installed} == {"silero-vad"}
    assert "silero-vad" not in {spec.id for spec in plan.missing}


def test_import_from_folder_picks_matching_names(tmp_path: Path, monkeypatch) -> None:
    manager = _manager_on(tmp_path, monkeypatch)
    source = tmp_path / "offline"
    source.mkdir()
    # Имя должно совпадать с последним элементом relative_path из реестра.
    (source / "silero_vad.onnx").write_bytes(b"fake-onnx")
    (source / "посторонний.txt").write_text("не модель", encoding="utf-8")

    imported = manager.import_from_folder("light", source)

    assert imported == ["silero-vad"]
    status = manager.status("silero-vad")
    assert status is not None and status.installed


def test_import_from_folder_rejects_file(tmp_path: Path, monkeypatch) -> None:
    manager = _manager_on(tmp_path, monkeypatch)
    victim = tmp_path / "not-a-folder.bin"
    victim.write_bytes(b"x")

    with pytest.raises(NotADirectoryError):
        manager.import_from_folder("light", victim)


def test_download_missing_skips_installed(tmp_path: Path, monkeypatch) -> None:
    manager = _manager_on(tmp_path, monkeypatch)
    source = tmp_path / "silero_vad.onnx"
    source.write_bytes(b"fake-onnx")
    manager.import_local("silero-vad", source)

    requested: list[str] = []

    def fake_download(model_id: str, progress=None) -> Path:
        requested.append(model_id)
        return tmp_path / model_id

    monkeypatch.setattr(manager, "download", fake_download)
    manager.download_missing("light")

    assert "silero-vad" not in requested
    assert requested
