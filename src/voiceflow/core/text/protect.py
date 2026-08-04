"""Защита фрагментов, которые нельзя менять.

Главный механизм выполнения требования «не искажать имена файлов, названия
библиотек, URL и команды». Такие фрагменты заменяются на короткие метки ещё
до очистки и до обращения к языковой модели, поэтому модель их просто не
видит и испортить не может. После обработки метки возвращаются на место.

Метка выглядит как ``⟦T1⟧``. Символы выбраны намеренно редкие: они не
встречаются в живой речи, а языковая модель не пытается их переводить.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: Обрамление метки. Меняется только вместе с ``TOKEN_PATTERN``.
TOKEN_OPEN = "⟦"
TOKEN_CLOSE = "⟧"
TOKEN_PATTERN = re.compile(r"⟦T\d+⟧")


def _pattern(source: str) -> re.Pattern[str]:
    return re.compile(source, re.IGNORECASE | re.UNICODE)


#: Правила в порядке приоритета: более длинные и специфичные идут раньше,
#: пересекающиеся совпадения отбрасываются.
RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Блок кода в тройных обратных кавычках; DOTALL нужен для переносов строк.
    ("code_block", re.compile(r"```.*?```", re.DOTALL)),
    # Код в одинарных обратных кавычках.
    ("code", _pattern(r"`[^`\n]+`")),
    # Адреса.
    ("url", _pattern(r"\b(?:https?://|ftp://|www\.)[^\s<>\"'»]+")),
    ("email", _pattern(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    # Пути Windows, в том числе сетевые.
    ("unc_path", _pattern(r"\\\\[^\s\\]+(?:\\[^\s\\]+)+")),
    ("win_path", _pattern(r"\b[A-Za-z]:\\[^\s\"'<>|]*")),
    # Пути POSIX и относительные пути.
    ("posix_path", _pattern(r"(?:\.{1,2})?/(?:[\w.-]+/)+[\w.-]+")),
    # Имя файла с расширением.
    ("filename", _pattern(r"\b[\w-]+\.(?:[A-Za-z][\w]{0,7})\b(?!\.)")),
    # Флаги командной строки.
    ("flag", _pattern(r"(?<![\w-])--?[A-Za-z][\w-]*")),
    # Версии: 1.2.3, v2.0
    ("version", _pattern(r"\bv?\d+\.\d+(?:\.\d+)*(?:-[\w.]+)?\b")),
    # Идентификаторы кода.
    ("snake_case", _pattern(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")),
    ("camel_case", re.compile(r"\b[a-z]+(?:[A-Z][a-z0-9]*)+\b")),
    ("pascal_case", re.compile(r"\b(?:[A-Z][a-z0-9]+){2,}\b")),
    ("constant", re.compile(r"\b[A-Z][A-Z0-9]{2,}(?:_[A-Z0-9]+)*\b")),
    # Числа с единицами измерения.
    ("measure", _pattern(r"\b\d+(?:[.,]\d+)?\s?(?:ГБ|МБ|КБ|GB|MB|KB|мс|ms|с|s|%)\b")),
)


@dataclass(frozen=True, slots=True)
class ProtectedText:
    """Текст с метками вместо неприкасаемых фрагментов."""

    text: str
    tokens: dict[str, str] = field(default_factory=dict)

    @property
    def token_count(self) -> int:
        return len(self.tokens)

    def restore(self, processed: str | None = None) -> str:
        """Возвращает исходные фрагменты на место меток."""
        return restore(self.text if processed is None else processed, self.tokens)


@dataclass(frozen=True, slots=True)
class _Match:
    start: int
    end: int
    kind: str
    value: str


def protect(text: str) -> ProtectedText:
    """Заменяет неприкасаемые фрагменты метками."""
    if not text:
        return ProtectedText(text="", tokens={})

    matches = _collect_matches(text)
    if not matches:
        return ProtectedText(text=text, tokens={})

    tokens: dict[str, str] = {}
    pieces: list[str] = []
    cursor = 0
    for index, span in enumerate(matches, start=1):
        token = f"{TOKEN_OPEN}T{index}{TOKEN_CLOSE}"
        tokens[token] = span.value
        pieces.append(text[cursor : span.start])
        pieces.append(token)
        cursor = span.end
    pieces.append(text[cursor:])

    return ProtectedText(text="".join(pieces), tokens=tokens)


def restore(text: str, tokens: dict[str, str]) -> str:
    """Возвращает исходные фрагменты на место меток."""
    if not tokens:
        return text
    result = text
    for token, value in tokens.items():
        result = result.replace(token, value)
    return result


def find_tokens(text: str) -> set[str]:
    """Метки, реально присутствующие в тексте."""
    return set(TOKEN_PATTERN.findall(text))


def missing_tokens(text: str, tokens: dict[str, str]) -> set[str]:
    """Метки, потерянные при обработке. Непустой ответ — повод для отката."""
    return set(tokens) - find_tokens(text)


def _collect_matches(text: str) -> list[_Match]:
    """Находит совпадения всех правил и отбрасывает пересекающиеся."""
    found: list[_Match] = []
    for kind, pattern in RULES:
        for hit in pattern.finditer(text):
            value = hit.group(0)
            if value:
                found.append(
                    _Match(start=hit.start(), end=hit.end(), kind=kind, value=value)
                )

    # Раньше начинается — важнее; при равном начале выигрывает более длинное.
    found.sort(key=lambda item: (item.start, -(item.end - item.start)))

    selected: list[_Match] = []
    last_end = -1
    for span in found:
        if span.start < last_end:
            continue
        selected.append(span)
        last_end = span.end
    return selected
