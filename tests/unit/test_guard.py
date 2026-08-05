"""Проверка ответа языковой модели.

Каждый тест соответствует конкретному способу, которым модель может испортить
текст. Это главная защита требования «не менять смысл».
"""

from __future__ import annotations

import pytest

from voiceflow.core.text.guard import Guard

ORIGINAL = "Надо добавить проверку входных данных и написать тест на неё."


@pytest.fixture
def guard() -> Guard:
    return Guard()


def test_good_answer_is_accepted(guard: Guard) -> None:
    verdict = guard.check(ORIGINAL, "Нужно добавить проверку входных данных и тест.")

    assert verdict.accepted is True
    assert verdict.reason == ""


def test_empty_answer_is_rejected(guard: Guard) -> None:
    verdict = guard.check(ORIGINAL, "   ")

    assert verdict.accepted is False
    assert verdict.text == ORIGINAL
    assert "пустой" in verdict.reason


def test_too_short_answer_is_rejected(guard: Guard) -> None:
    verdict = guard.check(ORIGINAL, "Надо.")

    assert verdict.accepted is False
    assert "короче" in verdict.reason


def test_too_long_answer_is_rejected(guard: Guard) -> None:
    """Модель начала фантазировать и дописывать требования."""
    verdict = guard.check(ORIGINAL, ORIGINAL + " " + "И ещё вот что важно. " * 10)

    assert verdict.accepted is False
    assert "длиннее" in verdict.reason


def test_lost_protected_fragment_is_rejected(guard: Guard) -> None:
    original = "Открой ⟦T1⟧ и проверь ⟦T2⟧ внимательно"
    tokens = {"⟦T1⟧": "main.py", "⟦T2⟧": "README.md"}

    verdict = guard.check(original, "Открой файл и проверь ⟦T2⟧ внимательно", tokens)

    assert verdict.accepted is False
    assert "защищённые фрагменты" in verdict.reason


def test_intact_fragments_are_accepted(guard: Guard) -> None:
    original = "Открой ⟦T1⟧ и проверь"
    tokens = {"⟦T1⟧": "main.py"}

    verdict = guard.check(original, "Открой ⟦T1⟧ и внимательно проверь", tokens)

    assert verdict.accepted is True


def test_lost_number_is_rejected(guard: Guard) -> None:
    original = "Поставь таймаут 30 секунд и повторов 5"

    verdict = guard.check(original, "Поставь таймаут и количество повторов")

    assert verdict.accepted is False
    assert "числа" in verdict.reason


def test_numbers_are_not_required_for_translation(guard: Guard) -> None:
    """При переводе «тридцать» законно превращается в «thirty»."""
    original = "Поставь таймаут 30 секунд"

    verdict = guard.check(
        original, "Set the timeout to thirty seconds", mode="translate"
    )

    assert verdict.accepted is True


@pytest.mark.parametrize(
    "prefix",
    ["Вот очищенный текст:", "Итоговый текст:", "Конечно:", "Here is:", "Перевод:"],
)
def test_meta_prefix_is_stripped(guard: Guard, prefix: str) -> None:
    verdict = guard.check(ORIGINAL, f"{prefix} Нужно добавить проверку и тест на неё.")

    assert verdict.accepted is True
    assert not verdict.text.startswith(prefix)


def test_answer_consisting_only_of_comment_is_rejected(guard: Guard) -> None:
    verdict = guard.check(ORIGINAL, "Вот очищенный текст:")

    assert verdict.accepted is False
    assert "комментарием" in verdict.reason


def test_code_fence_is_stripped(guard: Guard) -> None:
    verdict = guard.check(
        ORIGINAL, "```\nНужно добавить проверку входных данных и тест.\n```"
    )

    assert verdict.accepted is True
    assert "```" not in verdict.text


def test_wrapping_quotes_are_stripped(guard: Guard) -> None:
    verdict = guard.check(ORIGINAL, '"Нужно добавить проверку входных данных и тест."')

    assert verdict.accepted is True
    assert not verdict.text.startswith('"')


def test_inner_quotes_are_kept(guard: Guard) -> None:
    original = 'Он сказал "привет" и ушёл, потом вернулся обратно'
    candidate = 'Он сказал "привет" и ушёл, затем вернулся'

    verdict = guard.check(original, candidate)

    assert verdict.accepted is True
    assert '"привет"' in verdict.text


def test_translation_may_be_much_shorter(guard: Guard) -> None:
    original = "Мне нужно чтобы ты добавил обработку ошибок в этот модуль пожалуйста"

    verdict = guard.check(original, "Add error handling to this module.", mode="translate")

    assert verdict.accepted is True


def test_prompt_scaffold_echo_is_rejected(guard: Guard) -> None:
    """Реальный баг из истории Downloads: модель повторила шаблон инструкции."""
    original = (
        "Нужно исправить в трее, когда мы выбираем режим у нас трей закрывается. "
        "Этого не должно быть."
    )
    candidate = (
        "Собери из сказанного чёткую задачу:\n"
        "Нужно исправить поведение приложения.\n"
        "- При нажатии на любые настройки трей должен немедленно закрываться.\n"
    )

    verdict = guard.check(original, candidate, mode="prompt")

    assert verdict.accepted is False
    assert "правил" in verdict.reason


def test_multiline_wrapping_quotes_are_stripped(guard: Guard) -> None:
    original = "добавь проверку пароля и форму входа"
    candidate = (
        '"Реализовать вход в систему.\n\n'
        "Требования:\n"
        '- форма входа\n'
        '- проверка пароля"'
    )

    verdict = guard.check(original, candidate, mode="prompt")

    assert verdict.accepted is True
    assert not verdict.text.startswith('"')
    assert not verdict.text.endswith('"')


def test_instruction_mode_allows_expansion(guard: Guard) -> None:
    original = "надо сделать логин и чтобы пароль проверялся"
    candidate = (
        "Реализовать вход в систему.\n\n"
        "Требования:\n"
        "- форма входа\n"
        "- проверка пароля\n"
    )

    verdict = guard.check(original, candidate, mode="prompt")

    assert verdict.accepted is True


def test_unknown_mode_uses_default_bounds(guard: Guard) -> None:
    verdict = guard.check(ORIGINAL, ORIGINAL, mode="нет-такого")

    assert verdict.accepted is True


def test_rejected_answer_returns_the_original(guard: Guard) -> None:
    verdict = guard.check(ORIGINAL, "")

    assert verdict.text == ORIGINAL
