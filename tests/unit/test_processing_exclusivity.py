"""Взаимное исключение шагов перевода и инструкции."""

from __future__ import annotations

from voiceflow.core.settings.schema import ProcessingSettings
from voiceflow.core.text.modes import apply_step_enabled, enabled_steps


def test_enabling_prompt_disables_translate() -> None:
    settings = ProcessingSettings(
        clean_enabled=False, translate_enabled=True, prompt_mode_enabled=False
    )

    notes = apply_step_enabled(settings, "prompt", True)

    assert settings.prompt_mode_enabled is True
    assert settings.translate_enabled is False
    assert any("Перевод" in note for note in notes)
    assert [step.id for step in enabled_steps(settings)] == ["prompt"]


def test_enabling_translate_disables_prompt() -> None:
    settings = ProcessingSettings(translate_enabled=False, prompt_mode_enabled=True)

    apply_step_enabled(settings, "translate", True)

    assert settings.translate_enabled is True
    assert settings.prompt_mode_enabled is False


def test_clean_can_combine_with_prompt() -> None:
    settings = ProcessingSettings(clean_enabled=True, prompt_mode_enabled=False)

    apply_step_enabled(settings, "prompt", True)

    assert settings.clean_enabled is True
    assert settings.prompt_mode_enabled is True


def test_validate_disables_translate_when_both_on() -> None:
    from voiceflow.core.settings.schema import Settings, validate

    settings = Settings()
    settings.processing.translate_enabled = True
    settings.processing.prompt_mode_enabled = True

    notes = validate(settings)

    assert settings.processing.translate_enabled is False
    assert settings.processing.prompt_mode_enabled is True
    assert any("перевод" in note.casefold() for note in notes)
