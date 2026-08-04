"""Детерминированная очистка речи.

Работает без языковой модели, поэтому результат предсказуем и мгновенен.
Это базовый уровень: он выполняется всегда, а модель только полирует уже
очищенный текст. Если модель недоступна или её ответ не прошёл проверку,
пользователь всё равно получает вменяемый текст.

Правила намеренно осторожные. Любое сомнительное преобразование лучше не
делать, чем изменить смысл сказанного.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from voiceflow import paths

logger = logging.getLogger(__name__)

#: Минимальная длина оборванного слова, которое считается ложным началом.
#: Короче — слишком опасно: «про», «под», «на» бывают самостоятельными словами.
MIN_FALSE_START_LENGTH = 4

#: Насколько полное слово должно быть длиннее оборванного.
MIN_FALSE_START_GROWTH = 2

#: Сколько подряд идущих слов проверяется на повтор словосочетания.
MAX_REPEAT_PHRASE_WORDS = 3


@dataclass(frozen=True, slots=True)
class CleanupStats:
    """Что именно сделала очистка. Нужно для вкладки диагностики."""

    fillers_removed: int = 0
    repeats_collapsed: int = 0
    false_starts_removed: int = 0
    glossary_replacements: int = 0

    @property
    def total_changes(self) -> int:
        return (
            self.fillers_removed
            + self.repeats_collapsed
            + self.false_starts_removed
            + self.glossary_replacements
        )


@dataclass(frozen=True, slots=True)
class CleanupResult:
    text: str
    stats: CleanupStats


def load_fillers(path: Path | None = None) -> tuple[str, ...]:
    """Читает словарь слов-паразитов.

    Пользовательский файл дополняет заводской, а не заменяет его.
    """
    entries: list[str] = []
    factory = paths.config_dir() / "fillers.ru.txt" if path is None else path
    user = paths.user_config_root() / "fillers.ru.txt" if path is None else None

    for source in (factory, user):
        if source is None or not source.is_file():
            continue
        try:
            content = source.read_text(encoding="utf-8")
        except OSError:
            logger.exception("Не удалось прочитать словарь слов-паразитов %s", source)
            continue
        for line in content.splitlines():
            entry = line.strip()
            if entry and not entry.startswith("#"):
                entries.append(entry.lower())

    # Длинные записи должны срабатывать раньше коротких.
    unique = sorted(set(entries), key=lambda item: (-len(item), item))
    return tuple(unique)


@lru_cache(maxsize=8)
def _filler_pattern(fillers: tuple[str, ...]) -> re.Pattern[str] | None:
    if not fillers:
        return None
    alternatives = "|".join(_entry_to_pattern(entry) for entry in fillers)
    # Границы через классы символов: \b плохо работает рядом с дефисом.
    return re.compile(
        rf"(?<![^\W\d_-])(?:{alternatives})(?![^\W\d_-])",
        re.IGNORECASE | re.UNICODE,
    )


def _entry_to_pattern(entry: str) -> str:
    """Шаблон для одной записи словаря.

    Распознавание ставит «ё» непредсказуемо, поэтому обе буквы равноправны,
    а пробел в записи совпадает с любым их количеством.
    """
    escaped = re.escape(entry).replace(r"\ ", r"\s+")
    return escaped.replace("ё", "е").replace("е", "[её]")


def remove_fillers(text: str, fillers: tuple[str, ...]) -> tuple[str, int]:
    """Убирает слова-паразиты по словарю."""
    pattern = _filler_pattern(fillers)
    if pattern is None or not text:
        return text, 0
    result, count = pattern.subn(" ", text)
    return result, count


_WORD_SPLIT = re.compile(r"(\s+)")


def collapse_repeats(text: str) -> tuple[str, int]:
    """Схлопывает непосредственные повторы слов и коротких словосочетаний.

    «я я я думаю» -> «я думаю», «то есть то есть» -> «то есть».
    Повторы через другие слова не трогаем: там повтор обычно осмысленный.
    """
    tokens = [token for token in _WORD_SPLIT.split(text) if token]
    words = [(index, token) for index, token in enumerate(tokens) if not token.isspace()]
    if len(words) < 2:
        return text, 0

    drop: set[int] = set()
    removed = 0

    for size in range(MAX_REPEAT_PHRASE_WORDS, 0, -1):
        position = 0
        while position + 2 * size <= len(words):
            if any(index in drop for index, _ in words[position : position + 2 * size]):
                position += 1
                continue
            first = [_normalize_word(word) for _, word in words[position : position + size]]
            second = [
                _normalize_word(word)
                for _, word in words[position + size : position + 2 * size]
            ]
            if first == second and all(first):
                for index, _ in words[position : position + size]:
                    drop.add(index)
                removed += 1
                position += size
            else:
                position += 1

    if not drop:
        return text, 0

    kept: list[str] = []
    for index, token in enumerate(tokens):
        if index in drop:
            continue
        kept.append(token)
    return _tidy_spacing("".join(kept)), removed


def remove_false_starts(text: str) -> tuple[str, int]:
    """Убирает оборванные слова перед их полной формой.

    «прогр программа» -> «программа». Порог длины высокий намеренно: иначе
    пострадали бы предлоги, которые совпадают с началом следующего слова
    («про программу», «под подписью»).
    """
    tokens = [token for token in _WORD_SPLIT.split(text) if token]
    words = [(index, token) for index, token in enumerate(tokens) if not token.isspace()]
    drop: set[int] = set()
    removed = 0

    for position in range(len(words) - 1):
        index, current = words[position]
        _, following = words[position + 1]
        short = _normalize_word(current)
        full = _normalize_word(following)
        if not short or not full:
            continue
        if len(short) < MIN_FALSE_START_LENGTH:
            continue
        if len(full) - len(short) < MIN_FALSE_START_GROWTH:
            continue
        if full.startswith(short):
            drop.add(index)
            removed += 1

    if not drop:
        return text, 0

    kept = [token for index, token in enumerate(tokens) if index not in drop]
    return _tidy_spacing("".join(kept)), removed


_MULTI_SPACE = re.compile(r"[ \t\u00a0]{2,}")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.!?;:…])")
_REPEATED_COMMA = re.compile(r"(?:,\s*){2,}")
_LEADING_PUNCT = re.compile(r"^[\s,;:]+")
_PUNCT_AFTER_OPEN = re.compile(r"([(«\"])\s*[,;:]\s*")
_MISSING_SPACE = re.compile(r"([,.!?;:])(?=[^\s\d\)\]»\"'.,!?;:])")
_MULTI_DOT = re.compile(r"\.{4,}")


def normalize_punctuation(text: str) -> str:
    """Приводит пробелы и знаки препинания в порядок после удалений."""
    result = _MULTI_DOT.sub("…", text)
    result = _REPEATED_COMMA.sub(", ", result)
    result = _SPACE_BEFORE_PUNCT.sub(r"\1", result)
    result = _MISSING_SPACE.sub(r"\1 ", result)
    result = _PUNCT_AFTER_OPEN.sub(r"\1", result)
    result = _MULTI_SPACE.sub(" ", result)
    result = _LEADING_PUNCT.sub("", result)
    return result.strip()


_SENTENCE_START = re.compile(r"(^|[.!?…]\s+|\n\s*)([a-zа-яё])")


def capitalize_sentences(text: str) -> str:
    """Делает заглавной первую букву каждого предложения.

    Остальные буквы не трогаются: иначе пострадали бы аббревиатуры
    и названия вроде ``useEffect``.
    """
    return _SENTENCE_START.sub(lambda m: m.group(1) + m.group(2).upper(), text)


def clean(text: str, fillers: tuple[str, ...] | None = None) -> CleanupResult:
    """Полная детерминированная очистка."""
    if not text.strip():
        return CleanupResult(text="", stats=CleanupStats())

    dictionary = load_fillers() if fillers is None else fillers

    result, fillers_removed = remove_fillers(text, dictionary)
    result, false_starts = remove_false_starts(result)
    result, repeats = collapse_repeats(result)
    result = normalize_punctuation(result)
    result = capitalize_sentences(result)

    return CleanupResult(
        text=result,
        stats=CleanupStats(
            fillers_removed=fillers_removed,
            repeats_collapsed=repeats,
            false_starts_removed=false_starts,
        ),
    )


_TRIM_CHARS = " \t\n\r,.!?;:«»\"'()[]—–-…"


def _normalize_word(word: str) -> str:
    """Слово без знаков препинания, в нижнем регистре, «ё» приведена к «е»."""
    return word.strip(_TRIM_CHARS).lower().replace("ё", "е")


def _tidy_spacing(text: str) -> str:
    return _MULTI_SPACE.sub(" ", text).strip()
