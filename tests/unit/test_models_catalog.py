"""Реестр и менеджер моделей.

Отдельное внимание — соответствию реестра и движков: запись обязана доставлять
файлы туда, где движок их ищет. Расхождение здесь означает «скачано, но
приложение говорит, что модели нет».
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from voiceflow.core.models.catalog import KINDS, load_catalog, validate_spec
from voiceflow.core.models.manager import ModelDownloadError, ModelManager, verify_sha256


@pytest.fixture
def manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModelManager:
    from voiceflow.core.models import manager as manager_module

    monkeypatch.setattr(manager_module.paths, "models_dir", lambda: tmp_path / "models")
    monkeypatch.setattr(
        manager_module.paths, "whisper_models_dir", lambda: tmp_path / "models" / "whisper"
    )
    return ModelManager(load_catalog())


# --------------------------------------------------------------------------- #
# Реестр в репозитории
# --------------------------------------------------------------------------- #


def test_bundled_catalog_loads() -> None:
    catalog = load_catalog()

    assert catalog.by_id("silero-vad") is not None
    assert catalog.total_size("light") > 0


def test_every_entry_is_fully_described() -> None:
    """Опечатка в реестре должна ловиться здесь, а не у пользователя."""
    for spec in load_catalog().models:
        assert validate_spec(spec) == "", f"{spec.id}: {validate_spec(spec)}"
        assert spec.kind in KINDS
        assert spec.title, f"{spec.id}: нет названия"
        assert spec.presets or spec.required, f"{spec.id}: не привязан ни к одному пресету"


def test_sizes_are_filled() -> None:
    """Мастер показывает объём загрузки: ноль ввёл бы в заблуждение."""
    for spec in load_catalog().models:
        if spec.kind == "manual":
            continue
        assert spec.size_bytes > 0, f"{spec.id}: не указан размер"


def test_asr_entries_match_engine_model_names() -> None:
    """Идентификатор записи GigaAM обязан совпадать с именем модели onnx-asr."""
    from voiceflow.core.asr.gigaam_onnx import MODEL_BY_PRESET, MODEL_FILE_PREFIX

    catalog = load_catalog()
    for preset, model_name in MODEL_BY_PRESET.items():
        spec = catalog.by_id(model_name)
        assert spec is not None, f"в реестре нет модели «{model_name}» для пресета {preset}"
        assert preset in spec.presets, f"«{model_name}» не привязан к пресету {preset}"
        # Файлы, которые качает реестр, должны покрывать проверку движка.
        prefix = MODEL_FILE_PREFIX[model_name]
        assert any(name.startswith(prefix) for name in spec.patterns)


def test_gigaam_download_covers_engine_check(manager: ModelManager) -> None:
    """Скачанного набора должно хватить, чтобы движок счёл модель готовой."""
    from voiceflow.core.asr.gigaam_onnx import MODEL_FILE_PREFIX

    spec = manager.catalog.by_id("gigaam-v3-e2e-rnnt")
    assert spec is not None
    prefix = MODEL_FILE_PREFIX["gigaam-v3-e2e-rnnt"]
    # Движок требует веса и словарь; проверяем, что реестр качает и то, и то.
    assert any(n.startswith(prefix) and n.endswith(".onnx") for n in spec.patterns)
    assert f"{prefix}_vocab.txt" in spec.patterns


def test_whisper_entries_match_engine_repos() -> None:
    """Реестр и faster-whisper должны указывать на один репозиторий."""
    from voiceflow.core.asr.faster_whisper import MODEL_BY_PRESET

    catalog = load_catalog()
    whisper_repos = {s.repo for s in catalog.models if s.kind == "whisper"}
    for preset, repo in MODEL_BY_PRESET.items():
        assert repo in whisper_repos, f"репозиторий {repo} (пресет {preset}) отсутствует в реестре"


def test_wake_entry_matches_detector_path() -> None:
    from voiceflow.core.wake.vosk_grammar import MODEL_DIRNAME

    spec = load_catalog().by_id("vosk-small-ru")
    assert spec is not None
    assert spec.relative_path == f"wake/{MODEL_DIRNAME}"


def test_vad_entry_matches_expected_path() -> None:
    from voiceflow.core.audio.vad import MODEL_FILENAME

    spec = load_catalog().by_id("silero-vad")
    assert spec is not None
    assert spec.relative_path == f"vad/{MODEL_FILENAME}"


# --------------------------------------------------------------------------- #
# Готовность и план
# --------------------------------------------------------------------------- #


def test_nothing_installed_on_empty_machine(manager: ModelManager) -> None:
    plan = manager.download_plan("light")

    assert plan.installed == ()
    assert plan.missing
    assert not plan.is_complete
    assert plan.total_bytes > 0


def test_standard_preset_needs_no_manual_steps(manager: ModelManager) -> None:
    """Всё, без чего пресет не работает, должно ставиться само."""
    plan = manager.download_plan("standard")

    assert plan.manual == (), f"осталась ручная установка: {[s.title for s in plan.manual]}"
    assert "llama-server" in {spec.id for spec in plan.missing}


def test_manual_entries_are_separated(manager: ModelManager) -> None:
    """Записи без ссылки не попадают в очередь загрузки."""
    from voiceflow.core.models.catalog import ModelCatalog, ModelSpec

    spec = ModelSpec(
        id="ставится-руками",
        title="Ручная установка",
        purpose="runtime",
        presets=("standard",),
        size_bytes=0,
        kind="manual",
        relative_path="runtime/что-то",
    )
    plan = ModelManager(ModelCatalog(models=(spec,))).download_plan("standard")

    assert [s.id for s in plan.manual] == ["ставится-руками"]
    assert plan.missing == ()


def test_models_without_backend_are_skipped(
    manager: ModelManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Полтора гигабайта под неустановленный пакет качать незачем."""
    from voiceflow.core.models import catalog as catalog_module

    monkeypatch.setattr(
        catalog_module.ModelSpec, "backend_available", lambda self: self.requires == ""
    )
    plan = manager.download_plan("standard")

    ids = {spec.id for spec in plan.unavailable}
    assert "gigaam-v3-e2e-rnnt" in ids
    assert "gigaam-v3-e2e-rnnt" not in {spec.id for spec in plan.missing}


def test_url_model_counts_as_installed_when_file_exists(manager: ModelManager) -> None:
    spec = manager.catalog.by_id("silero-vad")
    assert spec is not None
    target = spec.local_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"fake-onnx")

    assert manager.is_installed(spec) is True
    status = manager.status("silero-vad")
    assert status is not None and status.installed and status.size_on_disk > 0


def test_zip_model_needs_non_empty_folder(manager: ModelManager) -> None:
    spec = manager.catalog.by_id("vosk-small-ru")
    assert spec is not None
    spec.local_path().mkdir(parents=True, exist_ok=True)

    assert manager.is_installed(spec) is False

    (spec.local_path() / "am").mkdir()
    assert manager.is_installed(spec) is True


def test_whisper_model_needs_model_bin(manager: ModelManager) -> None:
    spec = manager.catalog.by_id("whisper-large-v3-turbo")
    assert spec is not None
    folder = Path(str(spec.local_path().parent))  # не используется для whisper
    assert folder is not None

    from voiceflow.core.models import manager as manager_module

    cache = manager_module.paths.whisper_models_dir() / spec.cache_folder_name
    (cache / "snapshots" / "abc").mkdir(parents=True)
    assert manager.is_installed(spec) is False

    (cache / "snapshots" / "abc" / "model.bin").write_bytes(b"x")
    assert manager.is_installed(spec) is True


def test_preset_ready_requires_usable_asr(
    manager: ModelManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert manager.is_preset_ready("light") is False

    spec = manager.catalog.by_id("gigaam-v3-e2e-ctc")
    assert spec is not None
    monkeypatch.setattr(manager, "is_installed", lambda s: s.id == spec.id)
    from voiceflow.core.models import catalog as catalog_module

    monkeypatch.setattr(catalog_module.ModelSpec, "backend_available", lambda self: True)

    assert manager.is_preset_ready("light") is True


# --------------------------------------------------------------------------- #
# Ошибки загрузки
# --------------------------------------------------------------------------- #


def test_unknown_model_is_reported(manager: ModelManager) -> None:
    with pytest.raises(ModelDownloadError, match="нет модели"):
        manager.download("нет-такой")


def test_manual_model_explains_itself() -> None:
    from voiceflow.core.models.catalog import ModelCatalog, ModelSpec

    spec = ModelSpec(
        id="ставится-руками",
        title="Ручная установка",
        purpose="runtime",
        presets=("standard",),
        size_bytes=0,
        kind="manual",
        relative_path="runtime/что-то",
        notes="скачайте сами",
    )
    manual = ModelManager(ModelCatalog(models=(spec,)))

    with pytest.raises(ModelDownloadError, match="вручную"):
        manual.download("ставится-руками")


def test_missing_repository_gives_human_reason(manager: ModelManager) -> None:
    """401 от Hugging Face должен превращаться в понятную причину."""
    spec = manager.catalog.by_id("gigaam-v3-e2e-ctc")
    assert spec is not None

    message = ModelManager._explain(spec, RuntimeError("401 Client Error: Repository Not Found"))

    assert "недоступен" in message
    assert spec.repo in message


def test_network_failure_gives_human_reason(manager: ModelManager) -> None:
    spec = manager.catalog.by_id("silero-vad")
    assert spec is not None

    message = ModelManager._explain(spec, OSError("getaddrinfo failed"))

    assert "соединения" in message


def test_timeout_suggests_retry(manager: ModelManager) -> None:
    spec = manager.catalog.by_id("silero-vad")
    assert spec is not None

    message = ModelManager._explain(spec, TimeoutError("timed out"))

    assert "докачка" in message


# --------------------------------------------------------------------------- #
# Контрольные суммы и офлайн-установка
# --------------------------------------------------------------------------- #


def test_verify_sha256(tmp_path: Path) -> None:
    file = tmp_path / "model.bin"
    content = b"voiceflow-model"
    file.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()

    assert verify_sha256(file, digest) is True
    assert verify_sha256(file, "0" * 64) is False
    assert verify_sha256(file, "") is True


def test_import_from_folder_takes_matching_names(manager: ModelManager) -> None:
    source = Path(str(manager.catalog.by_id("silero-vad").local_path().parent.parent)) / "offline"
    source.mkdir(parents=True, exist_ok=True)
    (source / "silero_vad.onnx").write_bytes(b"fake-onnx")
    (source / "посторонний.txt").write_text("не модель", encoding="utf-8")

    imported = manager.import_from_folder("light", source)

    assert imported == ["silero-vad"]
    assert manager.status("silero-vad").installed is True


def test_asr_model_can_be_brought_on_a_flash_drive(manager: ModelManager) -> None:
    """Ради машины без интернета модели и лежат обычной папкой."""
    source = Path(str(manager.catalog.by_id("silero-vad").local_path().parent.parent)) / "offline2"
    prepared = source / "gigaam-v3-e2e-ctc"
    prepared.mkdir(parents=True)
    spec = manager.catalog.by_id("gigaam-v3-e2e-ctc")
    assert spec is not None
    for name in spec.patterns:
        (prepared / name).write_bytes(b"x")

    assert manager.import_from_folder("light", source) == ["gigaam-v3-e2e-ctc"]
    assert manager.is_installed(spec) is True


def test_import_skips_cache_kinds(manager: ModelManager) -> None:
    """Содержимое кэша Hugging Face так не переносится — обещать это нельзя."""
    source = Path(str(manager.catalog.by_id("silero-vad").local_path().parent.parent)) / "offline3"
    source.mkdir(parents=True, exist_ok=True)
    (source / "models--Systran--faster-whisper-small").mkdir()

    assert manager.import_from_folder("light", source) == []


def test_import_from_folder_rejects_file(manager: ModelManager, tmp_path: Path) -> None:
    victim = tmp_path / "not-a-folder.bin"
    victim.write_bytes(b"x")

    with pytest.raises(NotADirectoryError):
        manager.import_from_folder("light", victim)
