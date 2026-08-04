"""Выбор движка распознавания."""

from __future__ import annotations

import pytest

from tests.fakes import FakeTranscriber
from voiceflow.core.asr import registry as registry_module
from voiceflow.core.asr.base import TranscriberError
from voiceflow.core.asr.registry import (
    TranscriberRegistry,
    detect_device,
    select_engine,
)
from voiceflow.core.settings.schema import RecognitionSettings


def recognition(**kwargs: object) -> RecognitionSettings:
    settings = RecognitionSettings()
    for key, value in kwargs.items():
        setattr(settings, key, value)
    return settings


# --------------------------------------------------------------------------- #
# Правило выбора
# --------------------------------------------------------------------------- #


def test_manual_choice_wins() -> None:
    selection = select_engine(recognition(engine="whisper", primary_language="ru"))

    assert selection.engine == "whisper"
    assert "вручную" in selection.reason


def test_auto_language_requires_whisper() -> None:
    """GigaAM одноязычная и определять язык не умеет."""
    selection = select_engine(recognition(engine="auto", language_mode="auto"))

    assert selection.engine == "whisper"
    assert "автоопределение" in selection.reason


def test_russian_uses_gigaam() -> None:
    selection = select_engine(
        recognition(engine="auto", language_mode="fixed", primary_language="ru")
    )

    assert selection.engine == "gigaam"


def test_other_language_uses_whisper() -> None:
    selection = select_engine(
        recognition(engine="auto", language_mode="fixed", primary_language="en")
    )

    assert selection.engine == "whisper"


# --------------------------------------------------------------------------- #
# Устройство
# --------------------------------------------------------------------------- #


def test_light_preset_stays_on_cpu() -> None:
    """Лёгкий пресет существует ради машин без видеокарты."""
    assert detect_device("light") == "cpu"


def test_device_detection_uses_available_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    # onnxruntime — необязательная зависимость: без extras её в окружении нет.
    onnxruntime = pytest.importorskip("onnxruntime")

    monkeypatch.setattr(
        onnxruntime, "get_available_providers", lambda: ["CUDAExecutionProvider"]
    )
    assert detect_device("standard") == "cuda"

    monkeypatch.setattr(
        onnxruntime, "get_available_providers", lambda: ["CPUExecutionProvider"]
    )
    assert detect_device("standard") == "cpu"


# --------------------------------------------------------------------------- #
# Реестр
# --------------------------------------------------------------------------- #


@pytest.fixture
def fake_engines(monkeypatch: pytest.MonkeyPatch) -> dict[str, FakeTranscriber]:
    """Подменяет фабрики движков, чтобы не трогать настоящие модели."""
    engines = {
        "gigaam": FakeTranscriber(text="русский текст"),
        "whisper": FakeTranscriber(text="mixed text"),
    }
    engines["gigaam"].engine = "gigaam"
    engines["whisper"].engine = "whisper"

    monkeypatch.setattr(
        registry_module,
        "ENGINE_FACTORIES",
        {name: (lambda preset, device, e=engine: e) for name, engine in engines.items()},
    )
    return engines


def test_registry_returns_selected_engine(fake_engines: dict[str, FakeTranscriber]) -> None:
    store = TranscriberRegistry(lambda: recognition(engine="gigaam"))

    resolved = store.resolve()

    assert resolved.transcriber is fake_engines["gigaam"]
    assert resolved.note == ""


def test_registry_falls_back_when_model_missing(
    fake_engines: dict[str, FakeTranscriber],
) -> None:
    fake_engines["gigaam"].model_ready = False
    store = TranscriberRegistry(lambda: recognition(engine="gigaam"))

    resolved = store.resolve()

    assert resolved.transcriber is fake_engines["whisper"]
    assert "не загружена модель" in resolved.note
    # Исходный выбор пользователя в отчёте сохраняется.
    assert resolved.selection.engine == "gigaam"


def test_registry_falls_back_when_backend_missing(
    fake_engines: dict[str, FakeTranscriber],
) -> None:
    fake_engines["whisper"].backend_available = False
    store = TranscriberRegistry(lambda: recognition(engine="whisper"))

    resolved = store.resolve()

    assert resolved.transcriber is fake_engines["gigaam"]
    assert "не установлена библиотека" in resolved.note


def test_registry_reports_when_nothing_works(
    fake_engines: dict[str, FakeTranscriber],
) -> None:
    for engine in fake_engines.values():
        engine.model_ready = False
    store = TranscriberRegistry(lambda: recognition())

    with pytest.raises(TranscriberError, match="Откройте настройки"):
        store.resolve()


def test_registry_caches_instances(fake_engines: dict[str, FakeTranscriber]) -> None:
    store = TranscriberRegistry(lambda: recognition(engine="gigaam"))

    assert store.resolve().transcriber is store.resolve().transcriber


def test_invalidate_unloads_and_clears(fake_engines: dict[str, FakeTranscriber]) -> None:
    store = TranscriberRegistry(lambda: recognition(engine="gigaam"))
    store.resolve().transcriber.load()

    store.invalidate()

    assert fake_engines["gigaam"].is_loaded is False


def test_describe_all_lists_every_engine(fake_engines: dict[str, FakeTranscriber]) -> None:
    store = TranscriberRegistry(lambda: recognition())

    described = store.describe_all()

    assert len(described) == len(fake_engines)


def test_real_factories_cover_declared_engines() -> None:
    """Правило выбора не должно ссылаться на несуществующий движок."""
    from voiceflow.core.settings.schema import ASR_ENGINES

    for engine in ASR_ENGINES:
        if engine == "auto":
            continue
        assert engine in registry_module.ENGINE_FACTORIES
