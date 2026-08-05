"""Сборка текстового конвейера: цепочка включённых шагов."""

from __future__ import annotations

import pytest

from voiceflow.core.settings.schema import ProcessingSettings
from voiceflow.core.text.glossary import Glossary
from voiceflow.core.text.modes import STEPS, ProcessingStep, describe, enabled_steps, get_step
from voiceflow.core.text.processor import TextProcessor

FILLERS = ("ну", "как бы", "короче", "типа")


def settings_with(**flags: bool) -> ProcessingSettings:
    """Настройки с явно заданными шагами: по умолчанию все выключены."""
    base = ProcessingSettings(
        clean_enabled=False, translate_enabled=False, prompt_mode_enabled=False
    )
    for key, value in flags.items():
        setattr(base, key, value)
    return base


def make(
    settings: ProcessingSettings | None = None,
    glossary: Glossary | None = None,
    polisher=None,  # type: ignore[no-untyped-def]
) -> TextProcessor:
    resolved = settings if settings is not None else settings_with(clean_enabled=True)
    return TextProcessor(
        settings_provider=lambda: resolved,
        glossary_provider=lambda: glossary or Glossary(),
        fillers_provider=lambda: FILLERS,
        polisher=polisher,
    )


# --------------------------------------------------------------------------- #
# Реестр шагов
# --------------------------------------------------------------------------- #


def test_default_registry_order() -> None:
    assert [step.id for step in STEPS] == ["clean", "translate", "prompt"]


def test_enabled_steps_follow_switches() -> None:
    settings = settings_with(clean_enabled=True, prompt_mode_enabled=True)

    assert [step.id for step in enabled_steps(settings)] == ["clean", "prompt"]


def test_no_steps_enabled_gives_empty_chain() -> None:
    assert enabled_steps(settings_with()) == []


def test_every_step_flag_exists_in_settings() -> None:
    """Реестр шагов и схема настроек не должны разъезжаться."""
    for step in STEPS:
        assert hasattr(ProcessingSettings(), step.enabled_by)


def test_describe_explains_the_chain() -> None:
    assert describe(settings_with()) == "Дословный текст без обработки"
    assert "→" in describe(settings_with(clean_enabled=True, translate_enabled=True))


def test_get_step_returns_known_step() -> None:
    step = get_step("translate")
    assert step is not None and step.target_language == "en"


# --------------------------------------------------------------------------- #
# Пустая цепочка: дословный текст
# --------------------------------------------------------------------------- #


def test_all_steps_off_returns_text_as_is() -> None:
    processor = make(settings_with())

    result = processor.process("ну короче как бы текст")

    assert result.text == "ну короче как бы текст"
    assert result.steps == ()
    assert result.used_llm is False
    assert result.summary == "без обработки"


def test_all_steps_off_skips_polisher() -> None:
    calls: list[str] = []
    processor = make(settings_with(), polisher=lambda text, step: calls.append(step.id) or text)

    processor.process("текст")

    assert calls == []


# --------------------------------------------------------------------------- #
# Очистка правилами
# --------------------------------------------------------------------------- #


def test_clean_applies_rules() -> None:
    processor = make(settings_with(clean_enabled=True))

    result = processor.process("ну короче надо переделать")

    assert result.text == "Надо переделать"
    assert result.stats.fillers_removed == 2


def test_translate_without_clean_keeps_wording() -> None:
    """Без очистки правила не трогают текст: дословность важнее гладкости."""
    processor = make(settings_with(translate_enabled=True))

    result = processor.process("ну короче надо переделать")

    assert "короче" in result.text


# --------------------------------------------------------------------------- #
# Цепочка через языковую модель
# --------------------------------------------------------------------------- #


def _english_or_same(text: str, step: ProcessingStep) -> str:
    """Моки шагов с английским результатом: guard отклоняет кириллицу."""
    if step.id in ("translate", "prompt"):
        return f"English version of: {''.join(ch for ch in text if ord(ch) < 128) or 'ok'}"
    return text


def test_steps_run_in_order() -> None:
    seen: list[str] = []

    def polisher(text: str, step: ProcessingStep) -> str:
        seen.append(step.id)
        return _english_or_same(text, step)

    processor = make(
        settings_with(clean_enabled=True, translate_enabled=True, prompt_mode_enabled=True),
        polisher=polisher,
    )

    result = processor.process("надо переделать проект целиком до пятницы")

    assert seen == ["clean", "translate", "prompt"]
    assert result.steps == ("clean", "translate", "prompt")
    assert result.used_llm is True


def test_each_step_receives_previous_result() -> None:
    received: list[str] = []

    def polisher(text: str, step: ProcessingStep) -> str:
        received.append(text)
        base = _english_or_same(text, step)
        return f"{base} +{step.id}"

    processor = make(
        settings_with(clean_enabled=True, translate_enabled=True), polisher=polisher
    )

    processor.process("надо переделать проект целиком до пятницы")

    assert "+clean" in received[1]


def test_step_listener_reports_progress() -> None:
    announced: list[str] = []
    processor = make(
        settings_with(clean_enabled=True, translate_enabled=True),
        polisher=_english_or_same,
    )

    processor.process(
        "надо переделать проект целиком до пятницы",
        on_step=lambda step: announced.append(step.id),
    )

    assert announced == ["clean", "translate"]


def test_rejected_clean_does_not_block_later_steps() -> None:
    """Падение очистки моделью не должно обрывать перевод и инструкцию."""

    def polisher(text: str, step: ProcessingStep) -> str:
        if step.id == "clean":
            return ""
        return "Redo the whole project by Friday"

    processor = make(
        settings_with(clean_enabled=True, translate_enabled=True), polisher=polisher
    )

    result = processor.process("надо переделать проект целиком до пятницы")

    assert result.steps == ("translate",)
    assert "Friday" in result.text
    assert "Очистка" in result.fallback_reason


def test_rejected_translate_stops_the_chain() -> None:
    def polisher(text: str, step: ProcessingStep) -> str:
        if step.id == "translate":
            return ""
        return text

    processor = make(
        settings_with(clean_enabled=True, translate_enabled=True, prompt_mode_enabled=True),
        polisher=polisher,
    )

    result = processor.process("надо переделать проект целиком до пятницы")

    assert result.steps == ("clean",)
    assert "Перевод" in result.fallback_reason
    assert "prompt" not in result.steps


def test_failed_step_keeps_earlier_result() -> None:
    def polisher(text: str, step: ProcessingStep) -> str:
        if step.id == "translate":
            raise RuntimeError("модель не ответила")
        return text

    processor = make(
        settings_with(clean_enabled=True, translate_enabled=True), polisher=polisher
    )

    result = processor.process("надо переделать проект целиком до пятницы")

    assert result.steps == ("clean",)
    assert "модель не ответила" in result.fallback_reason


# --------------------------------------------------------------------------- #
# Защита технических фрагментов
# --------------------------------------------------------------------------- #


def test_technical_fragments_survive_cleanup() -> None:
    processor = make(settings_with(clean_enabled=True))

    result = processor.process("ну короче открой main.py и зайди на https://example.com")

    assert "main.py" in result.text
    assert "https://example.com" in result.text
    assert "короче" not in result.text
    assert result.protected_tokens == 2


def test_polisher_never_sees_protected_fragments() -> None:
    seen: list[str] = []

    def polisher(text: str, step: ProcessingStep) -> str:
        seen.append(text)
        return text

    processor = make(settings_with(clean_enabled=True), polisher=polisher)

    processor.process("открой файл main.py")

    assert "main.py" not in seen[0]
    assert "⟦T1⟧" in seen[0]


def test_polished_text_gets_fragments_back() -> None:
    def polisher(text: str, step: ProcessingStep) -> str:
        # Английский ответ с той же меткой: guard не пропустит кириллицу.
        return text.replace("открой", "Please open").replace("Открой", "Please open")

    processor = make(settings_with(translate_enabled=True), polisher=polisher)

    result = processor.process("открой main.py")

    assert "main.py" in result.text
    assert "Please open" in result.text
    assert result.used_llm is True


# --------------------------------------------------------------------------- #
# Словарь замен
# --------------------------------------------------------------------------- #


def test_glossary_is_applied() -> None:
    glossary = Glossary(replacements={"курсор": "Cursor"})
    processor = make(settings_with(clean_enabled=True), glossary=glossary)

    result = processor.process("открой курсор")

    assert "Cursor" in result.text
    assert result.stats.glossary_replacements == 1


def test_glossary_can_be_disabled() -> None:
    settings = settings_with(clean_enabled=True)
    settings.glossary_enabled = False
    processor = make(settings, glossary=Glossary(replacements={"курсор": "Cursor"}))

    result = processor.process("открой курсор")

    assert "Cursor" not in result.text


# --------------------------------------------------------------------------- #
# Языковая модель: отсутствие и сбои
# --------------------------------------------------------------------------- #


def test_missing_polisher_degrades_to_cleanup() -> None:
    processor = make(settings_with(clean_enabled=True, translate_enabled=True))

    result = processor.process("ну короче текст")

    assert result.used_llm is False
    assert result.fallback_reason == "языковая модель недоступна"
    assert result.text == "Текст"


def test_llm_can_be_switched_off_in_settings() -> None:
    settings = settings_with(clean_enabled=True)
    settings.use_llm = False
    processor = make(settings, polisher=lambda text, step: "не должно вызваться")

    result = processor.process("текст")

    assert result.used_llm is False
    assert "отключена" in result.fallback_reason


def test_summary_names_rule_cleanup_without_llm() -> None:
    """Без языковой модели очистка всё равно работает — сводка обязана это показать."""
    settings = settings_with(clean_enabled=True)
    settings.use_llm = False
    processor = make(settings)

    result = processor.process("это ну значит вот тест")

    assert result.rules_applied is True
    assert result.used_llm is False
    assert result.summary == "очистка правилами"


def test_summary_lists_rules_and_llm_steps() -> None:
    def polisher(text: str, step: ProcessingStep) -> str:
        if step.id == "translate":
            return "THIS MEANS THIS TEST"
        return text.upper()

    processor = make(
        settings_with(clean_enabled=True, translate_enabled=True),
        polisher=polisher,
    )

    result = processor.process("это ну значит вот тест")

    assert result.summary.startswith("очистка правилами → ")
    assert "translate" in result.summary


def test_summary_says_nothing_applied_when_all_steps_off() -> None:
    processor = make(settings_with())

    result = processor.process("текст без обработки")

    assert result.rules_applied is False
    assert result.summary == "без обработки"


def test_cleaned_text_is_reported_separately() -> None:
    """История хранит и очищенный, и итоговый текст."""

    def polisher(text: str, step: ProcessingStep) -> str:
        return "Final wording"

    processor = make(settings_with(clean_enabled=True), polisher=polisher)

    result = processor.process("ну короче надо переделать")

    assert result.cleaned == "Надо переделать"
    assert result.text == "Final wording"


def test_set_polisher_switches_behaviour() -> None:
    processor = make(settings_with(clean_enabled=True))
    assert processor.process("текст").used_llm is False

    processor.set_polisher(lambda text, step: text.upper())

    assert processor.process("текст").used_llm is True


def test_empty_input_stays_empty() -> None:
    processor = make(settings_with(clean_enabled=True))

    assert processor.process("   ").is_empty


# --------------------------------------------------------------------------- #
# Проверка одной инструкции
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("step", STEPS, ids=lambda step: step.id)
def test_preview_runs_single_step(step: ProcessingStep) -> None:
    seen: list[str] = []

    def polisher(text: str, s: ProcessingStep) -> str:
        seen.append(s.id)
        if s.id in ("translate", "prompt"):
            # Кириллицу убираем (иначе guard), метки ⟦T…⟧ оставляем.
            ascii_bits = "".join(ch if ord(ch) < 128 or ch in "⟦⟧" else " " for ch in text)
            return f"Open {ascii_bits} please"
        return f"{text}!"

    # Настройки все выключены: предпросмотр не должен на них смотреть.
    processor = make(settings_with(), polisher=polisher)

    result = processor.preview("надо открыть main.py", step.prompt_id)

    assert seen == [step.id]
    assert result.steps == (step.id,)
    assert "main.py" in result.text


def test_preview_ignores_disabled_llm_flag() -> None:
    settings = settings_with()
    settings.use_llm = False
    processor = make(settings, polisher=lambda text, step: f"{text}!")

    result = processor.preview("надо открыть проект", "clean.ru")

    assert result.used_llm is True


def test_preview_rejects_unknown_prompt() -> None:
    processor = make(settings_with())

    result = processor.preview("текст", "_shared_rules")

    assert result.steps == ()
    assert "не привязана" in result.fallback_reason
