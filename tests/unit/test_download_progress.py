"""Индикатор загрузки моделей.

Библиотека Hugging Face не сообщает прогресс наружу, поэтому объём считается
по файлам на диске. Проверяем, что счёт верен для каждого способа доставки:
без этого полоса стоит на месте и загрузка выглядит зависшей.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from voiceflow.core.models.catalog import ModelCatalog, ModelSpec, load_catalog
from voiceflow.core.models.manager import ModelManager, resolve_url


@pytest.fixture
def manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModelManager:
    from voiceflow.core.models import manager as manager_module

    monkeypatch.setattr(manager_module.paths, "models_dir", lambda: tmp_path / "models")
    monkeypatch.setattr(
        manager_module.paths, "whisper_models_dir", lambda: tmp_path / "models" / "whisper"
    )
    monkeypatch.setattr(
        manager_module, "_hub_cache_root", lambda: tmp_path / "models" / "hf" / "hub"
    )
    return ModelManager(load_catalog())


def test_nothing_downloaded_is_zero(manager: ModelManager) -> None:
    spec = manager.catalog.by_id("silero-vad")
    assert spec is not None

    assert manager.downloaded_bytes(spec) == 0


def test_partial_file_counts_toward_progress(manager: ModelManager) -> None:
    """Незавершённый файл — это уже скачанные байты, их нужно показывать."""
    spec = manager.catalog.by_id("silero-vad")
    assert spec is not None
    target = spec.local_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".partial")
    partial.write_bytes(b"x" * 4096)

    assert manager.downloaded_bytes(spec) == 4096


def test_finished_file_counts_fully(manager: ModelManager) -> None:
    spec = manager.catalog.by_id("silero-vad")
    assert spec is not None
    target = spec.local_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"x" * 9000)

    assert manager.downloaded_bytes(spec) == 9000


def test_asr_progress_counts_the_folder(manager: ModelManager) -> None:
    """Модели распознавания лежат обычной папкой, а не в кэше."""
    spec = manager.catalog.by_id("gigaam-v3-e2e-rnnt")
    assert spec is not None
    folder = spec.local_path()
    folder.mkdir(parents=True)
    (folder / "v3_e2e_rnnt_encoder.int8.onnx").write_bytes(b"x" * 1000)
    (folder / "v3_e2e_rnnt_encoder.int8.onnx.partial").write_bytes(b"x" * 500)

    assert manager.downloaded_bytes(spec) == 1500


def test_whisper_progress_counts_blobs_only(manager: ModelManager) -> None:
    """В snapshots лежит копия тех же данных: учёт обеих папок дал бы 200 %."""
    from voiceflow.core.models import manager as manager_module

    spec = manager.catalog.by_id("whisper-large-v3-turbo")
    assert spec is not None
    folder = manager_module.paths.whisper_models_dir() / spec.cache_folder_name
    (folder / "blobs").mkdir(parents=True)
    (folder / "snapshots" / "rev").mkdir(parents=True)
    (folder / "blobs" / "abc").write_bytes(b"x" * 1000)
    (folder / "snapshots" / "rev" / "model.bin").write_bytes(b"x" * 1000)

    assert manager.downloaded_bytes(spec) == 1000


def test_progress_counts_incomplete_blobs(manager: ModelManager) -> None:
    from voiceflow.core.models import manager as manager_module

    spec = manager.catalog.by_id("whisper-large-v3-turbo")
    assert spec is not None
    blobs = manager_module.paths.whisper_models_dir() / spec.cache_folder_name / "blobs"
    blobs.mkdir(parents=True)
    (blobs / "abc.incomplete").write_bytes(b"x" * 2048)

    assert manager.downloaded_bytes(spec) == 2048


def test_whisper_progress_uses_its_own_cache(manager: ModelManager) -> None:
    from voiceflow.core.models import manager as manager_module

    spec = manager.catalog.by_id("whisper-large-v3-turbo")
    assert spec is not None
    blobs = manager_module.paths.whisper_models_dir() / spec.cache_folder_name / "blobs"
    blobs.mkdir(parents=True)
    (blobs / "model").write_bytes(b"x" * 512)

    assert manager.downloaded_bytes(spec) == 512


def test_zip_progress_counts_archive_and_folder(manager: ModelManager) -> None:
    spec = manager.catalog.by_id("vosk-small-ru")
    assert spec is not None
    target = spec.local_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    (target.parent / f"{target.name}.zip.partial").write_bytes(b"x" * 700)

    assert manager.downloaded_bytes(spec) == 700


def test_progress_matches_declared_size(manager: ModelManager) -> None:
    """Проценты считаются от размера из реестра, поэтому он должен быть честным."""
    spec = manager.catalog.by_id("gigaam-v3-e2e-ctc")
    assert spec is not None
    folder = spec.local_path()
    folder.mkdir(parents=True)
    (folder / "v3_e2e_ctc.int8.onnx").write_bytes(b"x" * spec.size_bytes)

    assert manager.downloaded_bytes(spec) == spec.size_bytes


# --------------------------------------------------------------------------- #
# Прямая ссылка для больших файлов
# --------------------------------------------------------------------------- #


def test_resolve_url_points_at_the_file() -> None:
    spec = ModelSpec(
        id="llm",
        title="LLM",
        purpose="llm",
        presets=("standard",),
        size_bytes=1,
        kind="file",
        repo="Qwen/Qwen3-4B-GGUF",
        patterns=("Qwen3-4B-Q4_K_M.gguf",),
        relative_path="llm/model.gguf",
    )

    assert resolve_url(spec) == (
        "https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf"
    )


def test_large_files_are_fetched_directly(
    monkeypatch: pytest.MonkeyPatch, manager: ModelManager
) -> None:
    """Через huggingface_hub загрузка гигабайтных файлов из Xet останавливалась."""
    spec = manager.catalog.by_id("qwen3-4b")
    assert spec is not None

    used: dict[str, str] = {}

    def fake_fetch(self, model, destination, progress, url=""):  # type: ignore[no-untyped-def]
        used["url"] = url
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"gguf")

    monkeypatch.setattr(ModelManager, "_fetch", fake_fetch)
    manager.download("qwen3-4b")

    assert used["url"] == resolve_url(spec)
    assert spec.local_path().is_file()


def test_model_callback_reports_queue_position(
    monkeypatch: pytest.MonkeyPatch, manager: ModelManager
) -> None:
    """Интерфейсу нужно знать, за какой моделью следить и сколько их всего."""
    seen: list[tuple[str, int, int]] = []
    monkeypatch.setattr(ModelManager, "download", lambda self, model_id, progress=None: None)

    manager.download_missing(
        "light", on_model=lambda spec, index, count: seen.append((spec.id, index, count))
    )

    assert seen
    assert [item[1] for item in seen] == list(range(1, len(seen) + 1))
    assert {item[2] for item in seen} == {len(seen)}


def test_catalog_without_models_reports_nothing(tmp_path: Path) -> None:
    empty = ModelManager(ModelCatalog())

    assert empty.download_plan("light").missing == ()
