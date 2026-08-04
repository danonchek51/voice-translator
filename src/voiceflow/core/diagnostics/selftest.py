"""Четыре проверки для вкладки «Диагностика».

Каждая проверка работает с уже собранными подсистемами, а не создаёт свои:
микрофон уже открыт контроллером, движки уже кэшированы реестром. Поэтому
зависимости передаются аргументами — так проверки не поднимают второй поток
захвата и покрываются тестами без железа.

Проверки никогда не бросают исключение: неудача — это тоже результат,
который нужно показать пользователю понятным текстом.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from voiceflow.core.asr.base import TranscriberError

logger = logging.getLogger(__name__)

#: Текст для проверки обработки. Содержит слова-паразиты, повтор и путь к файлу,
#: чтобы сразу было видно и очистку, и сохранность неприкасаемого фрагмента.
SAMPLE_TEXT = (
    "ну вот значит нужно нужно поправить файл src/voiceflow/app.py "
    "и это самое перезапустить приложение"
)

#: Строка, которую проверка вставки отправляет в активное окно.
PASTE_PROBE = "VoiceFlow: проверка вставки"

#: Ниже этого пика сигнала нет вовсе: устройство отдаёт тишину.
SILENCE_PEAK = 0.001

#: Ниже этого пика речь распознаётся плохо — об этом стоит предупредить.
QUIET_PEAK = 0.02


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Итог одной проверки."""

    ok: bool
    title: str
    detail: str
    #: Что сделать, если проверка не прошла. Пусто, когда всё хорошо.
    hint: str = ""

    def as_line(self) -> str:
        mark = "OK" if self.ok else "ОШИБКА"
        line = f"{mark}: {self.title} — {self.detail}"
        return f"{line}\n{self.hint}" if self.hint else line


def check_microphone(
    capture: Any,
    seconds: float = 1.0,
    steps: int = 10,
    sleep: Callable[[float], None] = time.sleep,
) -> CheckResult:
    """Слушает уже открытый поток и смотрит, доходит ли сигнал."""
    if not capture.is_running:
        return CheckResult(
            ok=False,
            title="Микрофон",
            detail="Поток захвата закрыт",
            hint="Снимите «Паузу прослушивания» в меню трея и повторите проверку.",
        )

    peak = 0.0
    pause = seconds / max(1, steps)
    for _ in range(max(1, steps)):
        reading = capture.level
        peak = max(peak, float(reading.peak))
        sleep(pause)

    if peak <= SILENCE_PEAK:
        return CheckResult(
            ok=False,
            title="Микрофон",
            detail=f"Устройство открыто, но сигнала нет (пик {peak:.3f})",
            hint=(
                "Скажите что-нибудь во время проверки. Если тихо и дальше — "
                "проверьте выбранное устройство и системную громкость записи."
            ),
        )

    # Точность три знака: при двух едва слышный сигнал печатался как «0.00»
    # и выглядел прямым противоречием словам «сигнал есть».
    if peak < QUIET_PEAK:
        return CheckResult(
            ok=True,
            title="Микрофон",
            detail=f"Сигнал очень тихий, пик {peak:.3f}",
            hint=(
                "Для такого уровня распознавание будет ошибаться. Говорите ближе "
                "к микрофону или поднимите громкость записи в параметрах Windows."
            ),
        )

    return CheckResult(
        ok=True,
        title="Микрофон",
        detail=f"Сигнал есть, пиковый уровень {peak:.3f}",
    )


def check_recognition(transcribers: Any) -> CheckResult:
    """Проверяет, что хотя бы один движок готов работать."""
    try:
        resolved = transcribers.resolve()
    except TranscriberError as exc:
        return CheckResult(
            ok=False,
            title="Распознавание",
            detail=str(exc),
            hint="Откройте вкладку «Модели» и загрузите модель выбранного пресета.",
        )
    except Exception as exc:
        logger.exception("Проверка распознавания сорвалась")
        return CheckResult(
            ok=False,
            title="Распознавание",
            detail=f"Непредвиденная ошибка: {exc}",
            hint="Подробности в журнале приложения.",
        )

    info = resolved.transcriber.info()
    detail = f"{info.title}, модель {info.model_id}, устройство {info.device}"
    if resolved.note:
        detail = f"{detail}. {resolved.note}"
    return CheckResult(ok=True, title="Распознавание", detail=detail)


def check_processing(processor: Any, sample: str = SAMPLE_TEXT) -> CheckResult:
    """Прогоняет готовый текст через включённые шаги — микрофон не нужен."""
    try:
        result = processor.process(sample)
    except Exception as exc:
        logger.exception("Проверка обработки сорвалась")
        return CheckResult(
            ok=False,
            title="Обработка",
            detail=f"Сбой обработки: {exc}",
            hint="Подробности в журнале приложения.",
        )

    detail = result.text or "(пустой результат)"
    detail = f"{detail}\nПрименено: {result.summary}"
    if result.fallback_reason:
        # Откат guard и отключённая модель — штатная деградация, не ошибка.
        detail = f"{detail}\nБез языковой модели: {result.fallback_reason}"
    return CheckResult(ok=True, title="Обработка", detail=detail)


def check_paste(delivery: Any, text: str = PASTE_PROBE) -> CheckResult:
    """Кладёт тестовую строку в буфер и пытается вставить её в активное окно."""
    try:
        target = delivery.capture_target()
        outcome = delivery.deliver(text, target)
    except Exception as exc:
        logger.exception("Проверка вставки сорвалась")
        return CheckResult(
            ok=False,
            title="Вставка",
            detail=f"Сбой доставки: {exc}",
            hint="Подробности в журнале приложения.",
        )

    hint = ""
    if outcome.copied and not outcome.pasted:
        hint = (
            "Текст остался в буфере обмена — вставьте вручную через Ctrl+V. "
            "Так бывает с окнами от администратора и полноэкранными играми."
        )
    return CheckResult(
        ok=outcome.copied,
        title="Вставка",
        detail=outcome.message,
        hint=hint,
    )
