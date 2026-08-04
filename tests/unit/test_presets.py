"""Три пресета качества: описание и применение к настройкам."""

from __future__ import annotations

import pytest

from voiceflow.core.models.presets import (
    DEFAULT_PRESET,
    UnknownPresetError,
    apply_preset,
    get_preset,
    list_presets,
    matches,
)
from voiceflow.core.settings.schema import PRESETS, Settings


def test_all_schema_presets_are_described() -> None:
    described = [spec.id for spec in list_presets()]
    assert described == list(PRESETS)


def test_default_preset_is_known() -> None:
    assert get_preset(DEFAULT_PRESET).id == DEFAULT_PRESET


def test_unknown_preset_rejected() -> None:
    with pytest.raises(UnknownPresetError):
        get_preset("ultra")


def test_light_preset_turns_llm_off() -> None:
    settings = Settings()
    changes = apply_preset(settings, "light")

    assert settings.recognition.preset == "light"
    assert settings.recognition.engine == "gigaam"
    assert settings.processing.use_llm is False
    assert settings.llm.keep_loaded is False
    assert changes


def test_quality_preset_unloads_llm_between_requests() -> None:
    settings = Settings()
    apply_preset(settings, "quality")

    assert settings.recognition.engine == "whisper"
    assert settings.processing.use_llm is True
    # Модель 8B не помещается рядом с ASR, поэтому держать её в памяти нельзя.
    assert settings.llm.keep_loaded is False


def test_apply_is_idempotent() -> None:
    settings = Settings()
    apply_preset(settings, "light")

    assert apply_preset(settings, "light") == []


def test_matches_detects_manual_change() -> None:
    settings = Settings()
    apply_preset(settings, "light")
    assert matches(settings, "light")

    settings.processing.use_llm = True
    assert not matches(settings, "light")


def test_switching_preset_reports_changes() -> None:
    settings = Settings()
    apply_preset(settings, "light")
    changes = apply_preset(settings, "standard")

    assert any("пресет" in line for line in changes)
    assert settings.processing.use_llm is True
