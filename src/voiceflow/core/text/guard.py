"""Проверка ответа языковой модели.

Модель может добавить от себя, потерять защищённый фрагмент, начать ответ
с «Вот очищенный текст:» или просто уйти в сторону. Обязательное требование
продукта — не менять смысл, поэтому подозрительный ответ отклоняется, и
пользователь получает результат детерминированной очистки.

Отклонение не считается ошибкой: это штатная деградация, о которой сообщают
спокойной подписью, а не красным сообщением.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from voiceflow.core.text.protect import missing_tokens

logger = logging.getLogger(__name__)

#: Границы длины по режимам: перевод и структурирование законно меняют объём.
LENGTH_BOUNDS: dict[str, tuple[float, float]] = {
    "clean": (0.4, 1.3),
    "translate": (0.3, 1.8),
    "prompt": (0.25, 2.5),
}
DEFAULT_BOUNDS = (0.3, 2.0)

#: Допуск в символах поверх относительных границ.
#: На коротких фразах отношение длин ничего не значит: замена одного слова
#: даёт полуторакратный рост. Допуск сверху щедрый, снизу узкий — потеря
#: содержимого опаснее, чем небольшое многословие.
UPPER_SLACK_CHARS = 40
LOWER_SLACK_CHARS = 10

#: Начала ответов, выдающие болтовню модели вместо результата.
META_PREFIXES: tuple[str, ...] = (
    "вот очищенный текст",
    "вот исправленный текст",
    "вот итоговый текст",
    "вот перевод",
    "вот инструкция",
    "итоговый текст",
    "очищенный текст",
    "перевод",
    "результат",
    "конечно",
    "разумеется",
    "хорошо,",
    "here is",
    "here's",
    "sure,",
    "certainly",
    "the translation",
    "translation",
)

#: Фразы из заводских инструкций: если они всплыли в ответе, модель
#: пересказала правила вместо результата. История пользователя это ловила.
PROMPT_SCAFFOLD_MARKERS: tuple[str, ...] = (
    "собери из сказанного",
    "поток мыслей человека",
    "поток мыслей:",
    "критически важно:",
    "перед тобой поток",
    "напиши инструкцию для другой ai-модели, описывающую, как исправить",
    "убедись, что инструкция не включает в себя элементы, относящиеся к процессу",
)

_NUMBER = re.compile(r"\d+")
_FENCE = re.compile(r"^```[\w-]*\n(.*)\n```$", re.DOTALL)


@dataclass(frozen=True, slots=True)
class GuardVerdict:
    """Решение по ответу модели."""

    accepted: bool
    text: str
    reason: str = ""


class Guard:
    """Валидатор ответа языковой модели."""

    def __init__(self, strict: bool = True) -> None:
        self._strict = strict

    def check(
        self,
        original: str,
        candidate: str,
        tokens: dict[str, str] | None = None,
        mode: str = "clean",
    ) -> GuardVerdict:
        """Проверяет ответ и при необходимости слегка его подчищает."""
        cleaned = _strip_wrappers(candidate)

        if not cleaned.strip():
            return self._reject(original, "модель вернула пустой ответ")

        cleaned, stripped_meta = _strip_meta_prefix(cleaned)
        if not cleaned.strip():
            return self._reject(original, "модель ответила только комментарием")
        if stripped_meta and self._strict:
            logger.debug("Из ответа модели срезано вступление")

        if mode == "prompt" and _contains_prompt_scaffold(cleaned):
            return self._reject(original, "модель повторила правила инструкции")

        lost = missing_tokens(cleaned, tokens or {})
        if lost:
            return self._reject(
                original,
                f"модель потеряла защищённые фрагменты ({len(lost)} шт.)",
            )

        low, high = LENGTH_BOUNDS.get(mode, DEFAULT_BOUNDS)
        length = len(cleaned)
        source_length = max(1, len(original))
        ratio = length / source_length
        if length < low * source_length - LOWER_SLACK_CHARS:
            return self._reject(original, f"ответ короче исходного в {1 / ratio:.1f} раза")
        if length > high * source_length + UPPER_SLACK_CHARS:
            return self._reject(original, f"ответ длиннее исходного в {ratio:.1f} раза")

        # Числа проверяем только там, где текст остаётся на том же языке:
        # при переводе «двадцать» законно превращается в «twenty».
        if mode in ("clean", "prompt"):
            lost_numbers = _missing_numbers(original, cleaned)
            if lost_numbers:
                return self._reject(
                    original,
                    f"из ответа пропали числа: {', '.join(sorted(lost_numbers)[:3])}",
                )

        return GuardVerdict(accepted=True, text=cleaned)

    def _reject(self, original: str, reason: str) -> GuardVerdict:
        logger.info("Ответ модели отклонён: %s", reason)
        return GuardVerdict(accepted=False, text=original, reason=reason)


def _contains_prompt_scaffold(text: str) -> bool:
    """Ответ пересказал заводской шаблон вместо инструкции пользователя."""
    lowered = text.casefold()
    return any(marker in lowered for marker in PROMPT_SCAFFOLD_MARKERS)


def _strip_wrappers(text: str) -> str:
    """Убирает блок кода и обрамляющие кавычки, которыми модель любит обёртывать."""
    result = text.strip()

    fenced = _FENCE.match(result)
    if fenced:
        result = fenced.group(1).strip()

    # Многострочный ответ часто целиком в одних кавычках — снимаем внешний слой,
    # даже если внутри есть другие кавычки: иначе в буфер уходит обёртка.
    if len(result) > 2 and result[0] == result[-1] and result[0] in "\"'":
        result = result[1:-1].strip()
    else:
        pairs = (("«", "»"), ("“", "”"))
        for opening, closing in pairs:
            if len(result) > 2 and result.startswith(opening) and result.endswith(closing):
                result = result[1:-1].strip()
                break
    return result


def _strip_meta_prefix(text: str) -> tuple[str, bool]:
    """Срезает вступление вида «Вот очищенный текст:» вместе с двоеточием."""
    lowered = text.lstrip().lower()
    for prefix in META_PREFIXES:
        if not lowered.startswith(prefix):
            continue
        remainder = text.lstrip()[len(prefix) :].lstrip()
        if remainder.startswith(":"):
            return remainder[1:].strip(), True
        # Без двоеточия это может быть началом осмысленного текста.
        if remainder.startswith("\n"):
            return remainder.strip(), True
    return text, False


def _missing_numbers(original: str, candidate: str) -> set[str]:
    """Числа, которые были в исходном тексте и пропали из ответа."""
    source = set(_NUMBER.findall(original))
    if not source:
        return set()
    return source - set(_NUMBER.findall(candidate))
