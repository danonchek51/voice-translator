"""Цвета и размеры плашки.

Держим здесь, чтобы подпись состояния, цвет точки и иконка в трее не
разъехались между собой. Базовые цвета берутся из общей палитры
:mod:`voiceflow.ui.style`, чтобы плашка и окно настроек выглядели одинаково.

Значения модуля меняются при смене темы: плашка и волна читают их в момент
отрисовки, поэтому новый цвет виден сразу, без перезапуска приложения.
Единственная копия состояния живёт здесь, а не расползается по виджетам.
"""

from __future__ import annotations

from dataclasses import dataclass

from voiceflow.core.state import STATE_LABELS, AppState
from voiceflow.ui.style import PALETTE, Palette, palette_for


@dataclass(frozen=True, slots=True)
class StateStyle:
    label: str
    #: Цвет точки-индикатора в формате ``#rrggbb``.
    color: str


#: Базовые размеры при масштабе 100 %.
BASE_WIDTH = 196
#: Высота увеличена под волну: полоске хватало пяти точек, волне нужно место,
#: иначе колебания не видны.
BASE_HEIGHT = 54
BASE_RADIUS = 14
BASE_FONT_PT = 9
BASE_WAVE_HEIGHT = 18

#: Активная палитра и производные от неё цвета. Обновляются в :func:`apply`.
CURRENT: Palette = PALETTE
BACKGROUND = PALETTE.surface
BORDER = PALETTE.line
TEXT = PALETTE.text
TEXT_DIM = PALETTE.text_dim
METER_BACKGROUND = PALETTE.line
METER_FILL = PALETTE.accent
METER_PEAK = PALETTE.warning
SUCCESS = PALETTE.success
WARNING = PALETTE.warning

STATE_STYLES: dict[AppState, StateStyle] = {}


def _rebuild(palette: Palette, overlay_color: str = "", wave_color: str = "") -> None:
    """Пересчитывает цвета под новую палитру."""
    global CURRENT, BACKGROUND, BORDER, TEXT, TEXT_DIM
    global METER_BACKGROUND, METER_FILL, METER_PEAK, SUCCESS, WARNING

    CURRENT = palette
    BACKGROUND = overlay_color or palette.surface
    BORDER = palette.line
    TEXT = palette.text
    TEXT_DIM = palette.text_dim
    METER_BACKGROUND = palette.line
    METER_FILL = wave_color or palette.accent
    METER_PEAK = palette.warning
    SUCCESS = palette.success
    WARNING = palette.warning

    STATE_STYLES.clear()
    STATE_STYLES.update(
        {
            AppState.IDLE: StateStyle(STATE_LABELS[AppState.IDLE], palette.text_faint),
            AppState.LISTENING: StateStyle(STATE_LABELS[AppState.LISTENING], palette.accent),
            AppState.RECORDING: StateStyle(STATE_LABELS[AppState.RECORDING], palette.danger),
            AppState.TRANSCRIBING: StateStyle(STATE_LABELS[AppState.TRANSCRIBING], "#a855f7"),
            AppState.PROCESSING: StateStyle(STATE_LABELS[AppState.PROCESSING], palette.warning),
            AppState.PASTING: StateStyle(STATE_LABELS[AppState.PASTING], palette.success),
            AppState.ERROR: StateStyle(STATE_LABELS[AppState.ERROR], palette.danger),
            AppState.PAUSED: StateStyle(STATE_LABELS[AppState.PAUSED], palette.text_faint),
        }
    )


_rebuild(PALETTE)


def apply(appearance) -> Palette:  # type: ignore[no-untyped-def]
    """Применяет настройки оформления. Возвращает получившуюся палитру."""
    palette = palette_for(appearance.theme, appearance.accent)
    _rebuild(palette, appearance.overlay_color, appearance.wave_color)
    return palette


def processing_label(step_id: str) -> str:
    """Подпись стадии обработки по шагу.

    Отдельных состояний для перевода и формулирования не заводим: разница
    только в надписи, а сама машина состояний остаётся простой.
    """
    from voiceflow.core.text.modes import RAW_LABEL, get_step

    if not step_id:
        return RAW_LABEL
    step = get_step(step_id)
    return step.progress_label if step else STATE_LABELS[AppState.PROCESSING]


def style_for(state: AppState) -> StateStyle:
    return STATE_STYLES.get(state, STATE_STYLES[AppState.IDLE])


def scaled(value: int, scale_percent: int) -> int:
    """Пересчитывает размер под выбранный масштаб плашки."""
    return max(1, round(value * scale_percent / 100))
