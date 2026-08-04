"""Пользовательский словарь замен.

Распознавание записывает английские термины кириллицей: «курсор», «питон»,
«гитхаб». Языковой модели такую правку доверять нельзя — она заодно перепишет
и всё остальное. Поэтому замены выполняются детерминированно, до обращения
к модели, по явному списку самого пользователя.
"""

from __future__ import annotations

import logging
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from voiceflow import paths

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Glossary:
    """Замены «как слышится» -> «как пишется»."""

    replacements: dict[str, str] = field(default_factory=dict)
    #: Замечания загрузки: битый файл, неверные типы значений.
    notes: list[str] = field(default_factory=list)
    _pattern: re.Pattern[str] | None = field(default=None, init=False, repr=False)
    _lookup: dict[str, str] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self._rebuild()

    @property
    def is_empty(self) -> bool:
        return not self.replacements

    @classmethod
    def load(cls, path: Path | None = None) -> Glossary:
        """Читает словарь пользователя. Отсутствие файла — нормальная ситуация."""
        target = paths.glossary_file() if path is None else path
        if not target.is_file():
            return cls()

        try:
            with target.open("rb") as handle:
                data = tomllib.load(handle)
        except (tomllib.TOMLDecodeError, OSError) as exc:
            logger.warning("Словарь замен не прочитан: %s", exc)
            return cls(notes=[f"Словарь замен не прочитан: {exc}"])

        raw = data.get("replacements")
        if not isinstance(raw, dict):
            return cls(notes=["В словаре замен нет раздела [replacements]"])

        replacements: dict[str, str] = {}
        notes: list[str] = []
        for key, value in raw.items():
            if not isinstance(value, str):
                notes.append(f"Замена «{key}» пропущена: значение должно быть строкой")
                continue
            if not key.strip():
                continue
            replacements[key.strip()] = value
        return cls(replacements=replacements, notes=notes)

    def apply(self, text: str) -> tuple[str, int]:
        """Применяет замены. Возвращает текст и число сработавших правил."""
        if self._pattern is None or not text:
            return text, 0

        count = 0

        def substitute(match: re.Match[str]) -> str:
            nonlocal count
            count += 1
            return self._lookup[_normalize(match.group(0))]

        return self._pattern.sub(substitute, text), count

    def _rebuild(self) -> None:
        self._lookup = {_normalize(key): value for key, value in self.replacements.items()}
        if not self._lookup:
            self._pattern = None
            return

        # Длинные записи первыми: «пул реквест» должен победить «пул».
        keys = sorted(self.replacements, key=lambda item: (-len(item), item))
        alternatives = "|".join(_key_to_pattern(key) for key in keys)
        # Границы по буквам: \b рядом с кириллицей и дефисом ведёт себя иначе.
        self._pattern = re.compile(
            rf"(?<![^\W\d_])(?:{alternatives})(?![^\W\d_])",
            re.IGNORECASE | re.UNICODE,
        )


def _normalize(value: str) -> str:
    """Ключ поиска: нижний регистр, «ё» как «е», один пробел между словами."""
    return re.sub(r"\s+", " ", value).strip().lower().replace("ё", "е")


def _key_to_pattern(key: str) -> str:
    """Шаблон для одной записи словаря.

    Распознавание пишет «ё» непредсказуемо, поэтому обе буквы считаются
    одинаковыми, а любые пробелы в записи совпадают с любым их количеством.
    """
    escaped = re.escape(_normalize(key))
    escaped = escaped.replace(r"\ ", r"\s+")
    return escaped.replace("е", "[её]")
