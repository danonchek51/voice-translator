"""Сборка текстового конвейера.

Обработка — одна цепочка, а не выбор одного режима. Порядок шагов:

1. защита неприкасаемых фрагментов метками;
2. детерминированная очистка по правилам — если очистка включена;
3. пользовательский словарь замен;
4. языковая модель по одному включённому шагу за раз: очистка, перевод,
   инструкция;
5. проверка ответа модели после каждого шага и откат при подозрении;
6. возврат неприкасаемых фрагментов на место.

Если не включён ни один шаг, пользователь получает дословный текст: это
осмысленный режим для диктовки кода и команд, а не вырожденный случай.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from voiceflow.core.settings.schema import ProcessingSettings
from voiceflow.core.text.glossary import Glossary
from voiceflow.core.text.guard import Guard
from voiceflow.core.text.modes import ProcessingStep, enabled_steps, step_for_prompt

# Импортируем функции, а не модули под псевдонимом: пакет переэкспортирует
# имена protect и clean, и псевдоним модуля разрешался бы в функцию или
# в модуль в зависимости от порядка импортов.
from voiceflow.core.text.protect import protect as protect_text
from voiceflow.core.text.rules import CleanupStats, load_fillers
from voiceflow.core.text.rules import clean as clean_text

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProcessedText:
    """Итог обработки."""

    text: str
    #: Шаги, которые действительно применились языковой моделью.
    steps: tuple[str, ...] = ()
    #: Текст после детерминированной очистки, до языковой модели.
    cleaned: str = ""
    #: Отработала ли очистка правилами. Она меняет текст и без языковой
    #: модели, поэтому в сводке её нельзя пропускать.
    rules_applied: bool = False
    used_llm: bool = False
    #: Почему модель не применялась или её ответ отклонён. Не ошибка.
    fallback_reason: str = ""
    stats: CleanupStats = field(default_factory=CleanupStats)
    protected_tokens: int = 0

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()

    @property
    def summary(self) -> str:
        """Что применилось. Для журнала, истории и диагностики."""
        parts: list[str] = []
        if self.rules_applied:
            parts.append("очистка правилами")
        parts.extend(self.steps)
        return " → ".join(parts) if parts else "без обработки"


#: Полировка текста языковой моделью. Получает текст с метками и шаг,
#: возвращает ответ модели как есть: проверяет его уже guard.
Polisher = Callable[[str, ProcessingStep], str]

#: Уведомление о начале шага: плашка меняет подпись на «Перевожу» и так далее.
StepListener = Callable[[ProcessingStep], None]


class TextProcessor:
    """Применяет включённые шаги обработки к распознанному тексту."""

    def __init__(
        self,
        settings_provider: Callable[[], ProcessingSettings],
        glossary_provider: Callable[[], Glossary] | None = None,
        fillers_provider: Callable[[], tuple[str, ...]] | None = None,
        polisher: Polisher | None = None,
        guard: Guard | None = None,
    ) -> None:
        self._settings_provider = settings_provider
        self._glossary_provider = glossary_provider or Glossary
        self._fillers_provider = fillers_provider or load_fillers
        self._polisher = polisher
        self._guard = guard or Guard()

    def set_polisher(self, polisher: Polisher | None) -> None:
        """Подключает или отключает полировку языковой моделью."""
        self._polisher = polisher

    # ------------------------------------------------------------------ #
    # Основной путь
    # ------------------------------------------------------------------ #

    def process(self, raw: str, on_step: StepListener | None = None) -> ProcessedText:
        """Прогоняет текст через все включённые шаги."""
        settings = self._settings_provider()
        steps = enabled_steps(settings)

        if not steps:
            stripped = raw.strip()
            return ProcessedText(text=stripped, cleaned=stripped)

        protected = protect_text(raw)
        working = protected.text
        stats = CleanupStats()

        # Правила чистят текст только тогда, когда очистка включена: при одном
        # переводе дословность важнее гладкости.
        if settings.clean_enabled:
            cleanup = clean_text(working, self._fillers_provider())
            working = cleanup.text
            stats = cleanup.stats

        if settings.glossary_enabled:
            working, replacements = self._glossary_provider().apply(working)
            stats = CleanupStats(
                fillers_removed=stats.fillers_removed,
                repeats_collapsed=stats.repeats_collapsed,
                false_starts_removed=stats.false_starts_removed,
                glossary_replacements=replacements,
            )

        cleaned_final = protected.restore(working)

        polished, applied, reason = self._run_steps(
            working, steps, settings, protected.tokens, on_step
        )

        return ProcessedText(
            text=protected.restore(polished),
            steps=applied,
            cleaned=cleaned_final,
            rules_applied=settings.clean_enabled or settings.glossary_enabled,
            used_llm=bool(applied),
            fallback_reason=reason,
            stats=stats,
            protected_tokens=protected.token_count,
        )

    def preview(self, raw: str, prompt_id: str) -> ProcessedText:
        """Прогоняет текст через один шаг — для редактора инструкций.

        Настройки при этом не учитываются: пользователь проверяет конкретную
        инструкцию, а не текущую конфигурацию.
        """
        step = step_for_prompt(prompt_id)
        if step is None:
            stripped = raw.strip()
            return ProcessedText(
                text=stripped,
                cleaned=stripped,
                fallback_reason="инструкция не привязана к шагу обработки",
            )

        protected = protect_text(raw)
        polished, applied, reason = self._run_steps(
            protected.text,
            [step],
            self._settings_provider(),
            protected.tokens,
            on_step=None,
            ignore_use_llm=True,
        )
        return ProcessedText(
            text=protected.restore(polished),
            steps=applied,
            cleaned=protected.restore(protected.text),
            used_llm=bool(applied),
            fallback_reason=reason,
            protected_tokens=protected.token_count,
        )

    # ------------------------------------------------------------------ #
    # Языковая модель
    # ------------------------------------------------------------------ #

    def _run_steps(
        self,
        text: str,
        steps: list[ProcessingStep],
        settings: ProcessingSettings,
        tokens: dict[str, str],
        on_step: StepListener | None,
        ignore_use_llm: bool = False,
    ) -> tuple[str, tuple[str, ...], str]:
        """Возвращает текст, применённые шаги и причину отказа."""
        if not settings.use_llm and not ignore_use_llm:
            return text, (), "языковая модель отключена в настройках"
        if self._polisher is None:
            return text, (), "языковая модель недоступна"

        current = text
        applied: list[str] = []
        reasons: list[str] = []

        for step in steps:
            if on_step is not None:
                try:
                    on_step(step)
                except Exception:
                    logger.exception("Слушатель шага обработки завершился ошибкой")

            try:
                candidate = self._polisher(current, step)
            except Exception as exc:
                logger.warning("Шаг «%s» не выполнен: %s", step.id, exc)
                reasons.append(f"{step.title}: модель не ответила")
                # Дальше идти нет смысла: следующий шаг ждёт результат этого.
                break

            verdict = self._guard.check(
                original=current, candidate=candidate, tokens=tokens, mode=step.id
            )
            if not verdict.accepted:
                reasons.append(f"{step.title}: {verdict.reason}")
                break

            current = verdict.text
            applied.append(step.id)

        return current, tuple(applied), "; ".join(reasons)
