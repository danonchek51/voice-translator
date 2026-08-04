"""Нечёткое сравнение фразы активации."""

from __future__ import annotations

from voiceflow.core.wake.matcher import (
    levenshtein,
    normalize_phrase,
    phrase_risk,
    phrases_match,
)


def test_normalize_yo_and_case() -> None:
    assert normalize_phrase("Слушай Сюда!") == "слушай сюда"
    assert normalize_phrase("ёлка") == "елка"


def test_normalize_latin_transliteration() -> None:
    assert normalize_phrase("cursor") == "курсор"


def test_exact_match() -> None:
    assert phrases_match("слушай сюда", "Слушай сюда!", sensitivity=1)


def test_small_typo_matches_at_medium_sensitivity() -> None:
    assert phrases_match("слушай сида", "слушай сюда", sensitivity=5)


def test_unrelated_phrase_rejected() -> None:
    assert not phrases_match("доброе утро", "слушай сюда", sensitivity=10)


def test_short_word_does_not_match_long_phrase() -> None:
    # Короткое слово не должно ловиться внутри более длинной фразы как «совпадение».
    assert not phrases_match("давай поговорим", "да", sensitivity=5)


def test_levenshtein_basic() -> None:
    assert levenshtein("kitten", "sitting") == 3
    assert levenshtein("", "abc") == 3


def test_phrase_risk() -> None:
    assert phrase_risk("да") == "высокий"
    assert phrase_risk("слушай сюда") == "низкий"
