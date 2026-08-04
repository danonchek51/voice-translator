"""Детерминированная очистка речи."""

from __future__ import annotations

import pytest

from voiceflow.core.text.rules import (
    capitalize_sentences,
    clean,
    collapse_repeats,
    load_fillers,
    normalize_punctuation,
    remove_false_starts,
    remove_fillers,
)

FILLERS = ("ну", "как бы", "короче", "типа", "это самое", "э-э", "ммм")


# --------------------------------------------------------------------------- #
# Слова-паразиты
# --------------------------------------------------------------------------- #


def test_single_filler_is_removed() -> None:
    result, count = remove_fillers("ну надо сделать", FILLERS)

    assert count == 1
    assert "ну" not in result.split()


def test_multiword_filler_is_removed() -> None:
    result, count = remove_fillers("это как бы важно", FILLERS)

    assert count == 1
    assert "как бы" not in result


def test_longer_filler_wins_over_shorter() -> None:
    result, _ = remove_fillers("это самое надо", ("это", "это самое"))

    assert "это" not in result


def test_filler_inside_word_is_kept() -> None:
    """«ну» внутри «нужно» удалять нельзя."""
    result, count = remove_fillers("нужно сделать", FILLERS)

    assert count == 0
    assert result == "нужно сделать"


def test_case_is_ignored() -> None:
    _, count = remove_fillers("Короче говоря", ("короче",))

    assert count == 1


def test_empty_dictionary_changes_nothing() -> None:
    result, count = remove_fillers("любой текст", ())

    assert (result, count) == ("любой текст", 0)


def test_repository_dictionary_loads() -> None:
    fillers = load_fillers()

    assert "как бы" in fillers
    assert "короче" in fillers
    # Значимые слова по умолчанию выключены.
    assert "это" not in fillers
    assert "вот" not in fillers


def test_dictionary_is_sorted_longest_first() -> None:
    fillers = load_fillers()

    lengths = [len(entry) for entry in fillers]
    assert lengths == sorted(lengths, reverse=True)


# --------------------------------------------------------------------------- #
# Повторы
# --------------------------------------------------------------------------- #


def test_repeated_word_is_collapsed() -> None:
    result, count = collapse_repeats("я я я думаю что да")

    assert result == "я думаю что да"
    assert count == 2


def test_repeated_phrase_is_collapsed() -> None:
    result, count = collapse_repeats("то есть то есть надо переделать")

    assert result == "то есть надо переделать"
    assert count == 1


def test_repeat_through_other_words_is_kept() -> None:
    """«надо сделать надо проверить» — осмысленный повтор."""
    result, count = collapse_repeats("надо сделать надо проверить")

    assert count == 0
    assert result == "надо сделать надо проверить"


def test_case_and_yo_are_ignored_in_repeats() -> None:
    """Распознавание ставит «ё» непредсказуемо, повтор всё равно должен схлопнуться."""
    result, count = collapse_repeats("Всё все хорошо")

    assert count == 1
    assert result == "все хорошо"


def test_single_word_is_untouched() -> None:
    assert collapse_repeats("привет") == ("привет", 0)


# --------------------------------------------------------------------------- #
# Ложные начала
# --------------------------------------------------------------------------- #


def test_truncated_word_before_full_form_is_removed() -> None:
    result, count = remove_false_starts("прогр программа не работает")

    assert result == "программа не работает"
    assert count == 1


def test_short_preposition_is_kept() -> None:
    """«про программу» — предлог, а не оборванное слово."""
    result, count = remove_false_starts("про программу расскажи")

    assert count == 0
    assert result == "про программу расскажи"


def test_similar_but_not_prefix_is_kept() -> None:
    _, count = remove_false_starts("работа работник")

    assert count == 0


def test_barely_longer_word_is_kept() -> None:
    """Разница в один символ — обычно это форма слова, а не оговорка."""
    _, count = remove_false_starts("сдела сделал")

    assert count == 0


# --------------------------------------------------------------------------- #
# Пунктуация и регистр
# --------------------------------------------------------------------------- #


def test_double_spaces_are_collapsed() -> None:
    assert normalize_punctuation("много    пробелов") == "много пробелов"


def test_space_before_punctuation_is_removed() -> None:
    assert normalize_punctuation("текст , ещё") == "текст, ещё"


def test_repeated_commas_are_collapsed() -> None:
    assert normalize_punctuation("текст , , , ещё") == "текст, ещё"


def test_leading_punctuation_is_removed() -> None:
    assert normalize_punctuation(", , надо сделать") == "надо сделать"


def test_missing_space_after_comma_is_added() -> None:
    assert normalize_punctuation("раз,два") == "раз, два"


def test_decimal_number_keeps_its_dot() -> None:
    assert normalize_punctuation("версия 1.5 готова") == "версия 1.5 готова"


def test_long_ellipsis_is_normalized() -> None:
    assert normalize_punctuation("думаю..... да") == "думаю… да"


def test_sentences_are_capitalized() -> None:
    assert capitalize_sentences("привет. как дела? хорошо") == "Привет. Как дела? Хорошо"


def test_acronyms_are_not_lowercased() -> None:
    assert capitalize_sentences("это API работает") == "Это API работает"


def test_placeholder_at_sentence_start_is_left_alone() -> None:
    assert capitalize_sentences("⟦T1⟧ надо открыть") == "⟦T1⟧ надо открыть"


# --------------------------------------------------------------------------- #
# Полная очистка
# --------------------------------------------------------------------------- #


def test_full_cleanup_combines_rules() -> None:
    raw = "ну короче я я думаю что надо , , это как бы переделать"

    result = clean(raw, FILLERS)

    # «это» намеренно остаётся: его нет в консервативном словаре.
    assert result.text == "Я думаю что надо, это переделать"
    assert result.stats.fillers_removed >= 3
    assert result.stats.repeats_collapsed == 1
    assert result.stats.total_changes > 0


def test_empty_input_yields_empty_result() -> None:
    result = clean("   ", FILLERS)

    assert result.text == ""
    assert result.stats.total_changes == 0


def test_clean_text_is_left_almost_untouched() -> None:
    raw = "Нужно добавить проверку входных данных."

    result = clean(raw, FILLERS)

    assert result.text == raw
    assert result.stats.total_changes == 0


@pytest.mark.parametrize("hesitation", ["э-э", "ммм"])
def test_hesitations_are_removed(hesitation: str) -> None:
    result = clean(f"надо {hesitation} подумать", FILLERS)

    assert hesitation not in result.text
