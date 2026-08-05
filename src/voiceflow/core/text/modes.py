"""Реестр шагов обработки текста.

Обработка — одна цепочка: каждый шаг включается галочкой, порядок задаётся
настройкой. Все галочки выключены — пользователь получает дословный текст.

Типичные цепочки:

* очистка → инструкция — русская диктовка превращается в английский промпт;
* очистка → перевод — чистый английский текст;
* очистка → перевод → инструкция — сначала английский, потом структура промпта.

Добавление шага — запись здесь и файл инструкции в ``config/prompts``.
"""

from __future__ import annotations

from dataclasses import dataclass

from voiceflow.core.settings.schema import ProcessingSettings


@dataclass(frozen=True, slots=True)
class ProcessingStep:
    """Один шаг обработки."""

    id: str
    title: str
    description: str
    #: Файл инструкции в ``config/prompts`` без расширения.
    prompt_id: str
    #: Имя настройки, которая включает шаг.
    enabled_by: str
    #: Подпись на плашке, пока шаг выполняется.
    progress_label: str
    #: Язык результата шага: ``ru``, ``en`` или пусто, если не меняется.
    target_language: str = ""


CLEAN = ProcessingStep(
    id="clean",
    title="Очистка",
    description=(
        "Убирает слова-паразиты, повторы и ложные начала, сохраняя смысл "
        "и технические термины."
    ),
    prompt_id="clean.ru",
    enabled_by="clean_enabled",
    progress_label="Очищаю",
    target_language="ru",
)

TRANSLATE = ProcessingStep(
    id="translate",
    title="Перевод на английский",
    description=(
        "Переводит результат на естественный английский. "
        "Нужна скачанная языковая модель."
    ),
    prompt_id="translate.en",
    enabled_by="translate_enabled",
    progress_label="Перевожу",
    target_language="en",
)

PROMPT = ProcessingStep(
    id="prompt",
    title="Инструкция для AI",
    description=(
        "Из русской (или смешанной) диктовки делает готовую английскую "
        "инструкцию для другой модели. Нужна скачанная языковая модель: "
        "без неё шаг не работает, и вставится русский текст."
    ),
    prompt_id="prompt_engineer",
    enabled_by="prompt_mode_enabled",
    progress_label="Формулирую",
    target_language="en",
)

#: Заводской порядок. Пользователь может его менять в настройках.
DEFAULT_STEP_ORDER: tuple[str, ...] = ("clean", "translate", "prompt")

STEPS: tuple[ProcessingStep, ...] = (CLEAN, TRANSLATE, PROMPT)

STEPS_BY_ID: dict[str, ProcessingStep] = {step.id: step for step in STEPS}

STEPS_BY_PROMPT: dict[str, ProcessingStep] = {step.prompt_id: step for step in STEPS}

#: Что показывать на плашке, когда включённых шагов нет.
RAW_LABEL = "Готовлю"


def get_step(step_id: str) -> ProcessingStep | None:
    return STEPS_BY_ID.get(step_id)


def step_for_prompt(prompt_id: str) -> ProcessingStep | None:
    """Шаг, который использует эту инструкцию. Нужен редактору инструкций."""
    return STEPS_BY_PROMPT.get(prompt_id)


def normalize_step_order(order: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """Оставляет известные шаги без повторов и дописывает пропущенные."""
    seen: set[str] = set()
    result: list[str] = []
    for step_id in order:
        if step_id in STEPS_BY_ID and step_id not in seen:
            seen.add(step_id)
            result.append(step_id)
    for step_id in DEFAULT_STEP_ORDER:
        if step_id not in seen:
            result.append(step_id)
    return tuple(result)


def apply_step_enabled(
    settings: ProcessingSettings, step_id: str, enabled: bool
) -> list[str]:
    """Включает или выключает шаг. Побочных выключений больше нет."""
    step = get_step(step_id)
    if step is None:
        return []
    setattr(settings, step.enabled_by, enabled)
    return []


def move_step(settings: ProcessingSettings, step_id: str, delta: int) -> bool:
    """Сдвигает шаг в порядке на ``delta`` позиций. ``True`` — порядок изменился."""
    order = list(normalize_step_order(settings.step_order))
    if step_id not in order:
        return False
    index = order.index(step_id)
    target = index + delta
    if target < 0 or target >= len(order):
        return False
    order[index], order[target] = order[target], order[index]
    settings.step_order = tuple(order)
    return True


def enabled_steps(settings: ProcessingSettings) -> list[ProcessingStep]:
    """Включённые шаги в порядке из настроек."""
    order = normalize_step_order(settings.step_order)
    return [
        STEPS_BY_ID[step_id]
        for step_id in order
        if getattr(settings, STEPS_BY_ID[step_id].enabled_by, False)
    ]


def is_enabled(step: ProcessingStep, settings: ProcessingSettings) -> bool:
    return bool(getattr(settings, step.enabled_by, False))


def describe(settings: ProcessingSettings) -> str:
    """Короткое описание того, что произойдёт с текстом. Для интерфейса."""
    steps = enabled_steps(settings)
    if not steps:
        return "Дословный текст без обработки"
    return " → ".join(step.title for step in steps)
