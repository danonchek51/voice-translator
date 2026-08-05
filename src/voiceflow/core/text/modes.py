"""Реестр шагов обработки текста.

Выбора режима у пользователя нет: обработка — это одна цепочка, в которой
каждый шаг включается своей галочкой. Порядок фиксирован и осмыслен:
сначала текст приводится в порядок, потом при желании переводится, потом
при желании превращается в инструкцию.

Все галочки выключены — пользователь получает дословный текст.

Добавление шага — это запись здесь и файл инструкции в ``config/prompts``.
Конвейер при этом не меняется.
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
    description="Переводит результат на естественный английский.",
    prompt_id="translate.en",
    enabled_by="translate_enabled",
    progress_label="Перевожу",
    target_language="en",
)

PROMPT = ProcessingStep(
    id="prompt",
    title="Инструкция для AI",
    description=(
        "Превращает поток мыслей в краткую структурированную инструкцию "
        "для другой модели. Нельзя включать вместе с переводом: получится "
        "каша из двух задач."
    ),
    prompt_id="prompt_engineer",
    enabled_by="prompt_mode_enabled",
    progress_label="Формулирую",
)

#: Порядок применения. Менять его нельзя не подумав: перевод после
#: формулирования дал бы английскую инструкцию, собранную по русским правилам.
STEPS: tuple[ProcessingStep, ...] = (CLEAN, TRANSLATE, PROMPT)

STEPS_BY_ID: dict[str, ProcessingStep] = {step.id: step for step in STEPS}

STEPS_BY_PROMPT: dict[str, ProcessingStep] = {step.prompt_id: step for step in STEPS}

#: Перевод и «Инструкция» решают разные задачи. Вместе в истории пользователя
#: давали ответ, где модель повторяла свой шаблон вместо текста.
EXCLUSIVE_STEP_IDS: frozenset[str] = frozenset({"translate", "prompt"})

#: Что показывать на плашке, когда включённых шагов нет.
RAW_LABEL = "Готовлю"


def get_step(step_id: str) -> ProcessingStep | None:
    return STEPS_BY_ID.get(step_id)


def step_for_prompt(prompt_id: str) -> ProcessingStep | None:
    """Шаг, который использует эту инструкцию. Нужен редактору инструкций."""
    return STEPS_BY_PROMPT.get(prompt_id)


def apply_step_enabled(
    settings: ProcessingSettings, step_id: str, enabled: bool
) -> list[str]:
    """Включает или выключает шаг с учётом взаимных исключений.

    Возвращает список человекочитаемых побочных изменений (что выключили).
    """
    step = get_step(step_id)
    if step is None:
        return []

    notes: list[str] = []
    setattr(settings, step.enabled_by, enabled)
    if enabled and step_id in EXCLUSIVE_STEP_IDS:
        for other_id in EXCLUSIVE_STEP_IDS:
            if other_id == step_id:
                continue
            other = get_step(other_id)
            if other is None:
                continue
            if getattr(settings, other.enabled_by, False):
                setattr(settings, other.enabled_by, False)
                notes.append(f"выключен шаг «{other.title}»")
    return notes


def enabled_steps(settings: ProcessingSettings) -> list[ProcessingStep]:
    """Включённые шаги в порядке применения."""
    return [step for step in STEPS if getattr(settings, step.enabled_by, False)]


def is_enabled(step: ProcessingStep, settings: ProcessingSettings) -> bool:
    return bool(getattr(settings, step.enabled_by, False))


def describe(settings: ProcessingSettings) -> str:
    """Короткое описание того, что произойдёт с текстом. Для интерфейса."""
    steps = enabled_steps(settings)
    if not steps:
        return "Дословный текст без обработки"
    return " → ".join(step.title for step in steps)
