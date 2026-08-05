"""Порядок шагов обработки и совместная работа режимов."""

from __future__ import annotations

from voiceflow.core.settings.schema import ProcessingSettings, Settings, validate
from voiceflow.core.text.modes import (
    apply_step_enabled,
    enabled_steps,
    move_step,
    normalize_step_order,
)


def test_all_three_steps_can_be_enabled_together() -> None:
    settings = ProcessingSettings(
        clean_enabled=True, translate_enabled=True, prompt_mode_enabled=True
    )

    assert [step.id for step in enabled_steps(settings)] == [
        "clean",
        "translate",
        "prompt",
    ]


def test_step_order_can_be_changed() -> None:
    settings = ProcessingSettings(
        clean_enabled=True,
        translate_enabled=False,
        prompt_mode_enabled=True,
        step_order=("prompt", "clean", "translate"),
    )

    assert [step.id for step in enabled_steps(settings)] == ["prompt", "clean"]


def test_move_step_swaps_neighbours() -> None:
    settings = ProcessingSettings()
    assert move_step(settings, "clean", 1) is True
    assert settings.step_order[0] == "translate"
    assert settings.step_order[1] == "clean"


def test_normalize_step_order_fills_missing() -> None:
    assert normalize_step_order(("prompt",)) == ("prompt", "clean", "translate")


def test_apply_step_enabled_keeps_siblings() -> None:
    settings = ProcessingSettings(translate_enabled=True, prompt_mode_enabled=False)
    notes = apply_step_enabled(settings, "prompt", True)

    assert settings.prompt_mode_enabled is True
    assert settings.translate_enabled is True
    assert notes == []


def test_validate_keeps_translate_and_prompt_together() -> None:
    settings = Settings()
    settings.processing.translate_enabled = True
    settings.processing.prompt_mode_enabled = True
    settings.processing.step_order = ("prompt", "nope", "clean")

    notes = validate(settings)

    assert settings.processing.translate_enabled is True
    assert settings.processing.prompt_mode_enabled is True
    assert settings.processing.step_order == ("prompt", "clean", "translate")
    assert any("step_order" in note for note in notes)
