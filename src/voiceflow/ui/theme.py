"""Цвета и размеры плашки.

Держим здесь, чтобы подпись состояния, цвет точки и иконка в трее не
разъехались между собой. Базовые цвета берутся из общей палитры
:mod:`voiceflow.ui.style`, чтобы плашка и окно настроек выглядели одинаково.
"""

from __future__ import annotations

from dataclasses import dataclass

from voiceflow.core.state import STATE_LABELS, AppState
from voiceflow.ui.style import PALETTE


@dataclass(frozen=True, slots=True)
class StateStyle:
    label: str
    #: Цвет точки-индикатора в формате ``#rrggbb``.
    color: str


STATE_STYLES: dict[AppState, StateStyle] = {
    AppState.IDLE: StateStyle(STATE_LABELS[AppState.IDLE], PALETTE.text_faint),
    AppState.LISTENING: StateStyle(STATE_LABELS[AppState.LISTENING], PALETTE.accent),
    AppState.RECORDING: StateStyle(STATE_LABELS[AppState.RECORDING], PALETTE.danger),
    AppState.TRANSCRIBING: StateStyle(STATE_LABELS[AppState.TRANSCRIBING], "#a855f7"),
    AppState.PROCESSING: StateStyle(STATE_LABELS[AppState.PROCESSING], PALETTE.warning),
    AppState.PASTING: StateStyle(STATE_LABELS[AppState.PASTING], PALETTE.success),
    AppState.ERROR: StateStyle(STATE_LABELS[AppState.ERROR], "#dc2626"),
    AppState.PAUSED: StateStyle(STATE_LABELS[AppState.PAUSED], "#4b5563"),
}

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


#: Базовые размеры при масштабе 100 %.
BASE_WIDTH = 196
BASE_HEIGHT = 46
BASE_RADIUS = 14
BASE_FONT_PT = 9

BACKGROUND = PALETTE.surface
BORDER = PALETTE.line
TEXT = PALETTE.text
TEXT_DIM = PALETTE.text_dim
METER_BACKGROUND = PALETTE.line
METER_FILL = PALETTE.accent
METER_PEAK = PALETTE.warning


def style_for(state: AppState) -> StateStyle:
    return STATE_STYLES.get(state, STATE_STYLES[AppState.IDLE])


def scaled(value: int, scale_percent: int) -> int:
    """Пересчитывает размер под выбранный масштаб плашки."""
    return max(1, round(value * scale_percent / 100))
