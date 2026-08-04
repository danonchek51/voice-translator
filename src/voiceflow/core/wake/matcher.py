"""Нормализация и нечёткое сравнение фразы активации.

Сравнение идёт по нормализованной форме и расстоянию Левенштейна,
а не поиском подстроки: иначе короткое слово вроде «да» ловилось бы
внутри любой более длинной фразы.
"""

from __future__ import annotations

import re
import unicodedata

_PUNCT_RE = re.compile(r"[^\w\s]+", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")

#: Транслитерация латиницы для фразы активации в русском акустическом пространстве.
_LATIN_TO_CYRILLIC = str.maketrans(
    {
        "a": "а",
        "b": "б",
        "c": "к",
        "d": "д",
        "e": "е",
        "f": "ф",
        "g": "г",
        "h": "х",
        "i": "и",
        "j": "дж",
        "k": "к",
        "l": "л",
        "m": "м",
        "n": "н",
        "o": "о",
        "p": "п",
        "q": "к",
        "r": "р",
        "s": "с",
        "t": "т",
        "u": "у",
        "v": "в",
        "w": "в",
        "x": "кс",
        "y": "й",
        "z": "з",
    }
)


def normalize_phrase(text: str) -> str:
    """Приводит фразу к виду, пригодному для сравнения."""
    value = unicodedata.normalize("NFKC", text).casefold()
    value = value.replace("ё", "е")
    value = value.translate(_LATIN_TO_CYRILLIC)
    value = _PUNCT_RE.sub(" ", value)
    value = _SPACE_RE.sub(" ", value).strip()
    return value


def levenshtein(a: str, b: str) -> int:
    """Классическое расстояние редактирования."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            insert = current[j - 1] + 1
            delete = prev[j] + 1
            replace = prev[j - 1] + (0 if ca == cb else 1)
            current.append(min(insert, delete, replace))
        prev = current
    return prev[-1]


def max_distance_for_sensitivity(phrase: str, sensitivity: int) -> int:
    """Порог расстояния по длине фразы и чувствительности 1..10.

    1 — почти точное совпадение, 10 — заметно мягче.
    """
    sensitivity = max(1, min(10, sensitivity))
    length = max(1, len(normalize_phrase(phrase)))
    # База: не больше ~20 % длины, минимум 0, плюс бонус от чувствительности.
    base = max(0, length // 5)
    bonus = (sensitivity - 1) // 3
    return base + bonus


def phrases_match(heard: str, expected: str, sensitivity: int = 5) -> bool:
    """Совпадает ли услышанное с ожидаемой фразой."""
    left = normalize_phrase(heard)
    right = normalize_phrase(expected)
    if not left or not right:
        return False
    if left == right:
        return True
    return levenshtein(left, right) <= max_distance_for_sensitivity(right, sensitivity)


def phrase_risk(phrase: str) -> str:
    """Оценка риска ложных срабатываний для интерфейса настроек."""
    normalized = normalize_phrase(phrase)
    words = normalized.split()
    if not normalized:
        return "пусто"
    if len(words) == 1 and len(normalized) <= 4:
        return "высокий"
    if len(words) == 1:
        return "средний"
    return "низкий"
