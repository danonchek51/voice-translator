"""Защита неприкасаемых фрагментов.

Главное требование продукта: имена файлов, названия библиотек, URL и команды
не должны искажаться. Проверяем, что они вообще не доходят до обработки.
"""

from __future__ import annotations

import pytest

from voiceflow.core.text.protect import (
    TOKEN_PATTERN,
    find_tokens,
    missing_tokens,
    protect,
    restore,
)


@pytest.mark.parametrize(
    "fragment",
    [
        "https://example.com/path?a=1",
        "http://localhost:8080",
        "www.python.org",
        "user@example.com",
        r"C:\Users\input\main.py",
        r"\\server\share\file.txt",
        "./src/voiceflow/app.py",
        "/usr/local/bin/python",
        "main.py",
        "README.md",
        "--force",
        "-v",
        "1.2.3",
        "v2.0.1",
        "my_variable_name",
        "useEffect",
        "TextProcessor",
        "MAX_RETRIES",
        "16 ГБ",
        "150 мс",
    ],
)
def test_fragment_survives_round_trip(fragment: str) -> None:
    text = f"надо открыть {fragment} и посмотреть"

    protected = protect(text)

    assert fragment not in protected.text, "фрагмент должен быть скрыт меткой"
    assert protected.token_count == 1
    assert protected.restore() == text


def test_backtick_code_is_protected() -> None:
    text = "выполни `git commit -m fix` и всё"

    protected = protect(text)

    assert "git commit" not in protected.text
    assert protected.restore() == text


def test_code_block_is_protected() -> None:
    text = "смотри ```python\nprint(1)\n``` вот так"

    protected = protect(text)

    assert "print(1)" not in protected.text
    assert protected.restore() == text


def test_several_fragments_get_distinct_tokens() -> None:
    text = "открой main.py, потом README.md и зайди на https://example.com"

    protected = protect(text)

    assert protected.token_count == 3
    assert len(set(protected.tokens.values())) == 3
    assert protected.restore() == text


def test_plain_text_is_untouched() -> None:
    text = "надо переделать вот эту часть по-человечески"

    protected = protect(text)

    assert protected.text == text
    assert protected.token_count == 0


def test_empty_text() -> None:
    protected = protect("")

    assert protected.text == ""
    assert protected.token_count == 0


def test_overlapping_matches_are_resolved_once() -> None:
    """Путь содержит и имя файла, и точку с расширением — метка должна быть одна."""
    text = r"файл C:\project\src\main.py открой"

    protected = protect(text)

    assert protected.token_count == 1
    assert protected.restore() == text


def test_tokens_are_recognizable() -> None:
    protected = protect("открой main.py")

    tokens = find_tokens(protected.text)

    assert len(tokens) == 1
    assert all(TOKEN_PATTERN.fullmatch(token) for token in tokens)


def test_missing_tokens_detects_loss() -> None:
    """Так конвейер понимает, что модель испортила защищённый фрагмент."""
    protected = protect("открой main.py и README.md")
    damaged = next(iter(protected.tokens))

    lost = missing_tokens(protected.text.replace(damaged, "чушь"), protected.tokens)

    assert lost == {damaged}


def test_no_missing_tokens_when_intact() -> None:
    protected = protect("открой main.py")

    assert missing_tokens(protected.text, protected.tokens) == set()


def test_restore_without_tokens_returns_input() -> None:
    assert restore("просто текст", {}) == "просто текст"


def test_reordered_text_still_restores() -> None:
    """Модель может переставить фрагменты местами — метки всё равно вернутся."""
    protected = protect("сначала main.py потом README.md")
    first, second = list(protected.tokens)
    reordered = f"сначала {second} потом {first}"

    result = restore(reordered, protected.tokens)

    assert "README.md" in result
    assert "main.py" in result
    assert result.index("README.md") < result.index("main.py")


def test_russian_words_are_not_mistaken_for_identifiers() -> None:
    text = "надо просто сделать так чтобы всё работало"

    assert protect(text).token_count == 0
