"""Иконки рисуются кодом, а не хранятся файлами.

Так в репозиторий не попадают бинарные ресурсы, иконка автоматически
подстраивается под масштаб экрана и всегда соответствует цвету состояния.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from voiceflow.core.state import AppState
from voiceflow.ui import theme

_ICON_CACHE: dict[tuple[AppState, int], QIcon] = {}


def state_icon(state: AppState, size: int = 32) -> QIcon:
    """Иконка трея: кружок цвета состояния с силуэтом микрофона."""
    cache_key = (state, size)
    cached = _ICON_CACHE.get(cache_key)
    if cached is not None:
        return cached

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    color = QColor(theme.style_for(state).color)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(color))
    painter.drawEllipse(QRectF(1, 1, size - 2, size - 2))

    _draw_microphone(painter, size, QColor("#ffffff"))

    if state is AppState.PAUSED:
        _draw_slash(painter, size, QColor("#ffffff"))

    painter.end()

    icon = QIcon(pixmap)
    _ICON_CACHE[cache_key] = icon
    return icon


def _draw_microphone(painter: QPainter, size: int, color: QColor) -> None:
    unit = size / 32.0
    painter.setBrush(QBrush(color))
    painter.setPen(Qt.PenStyle.NoPen)

    capsule = QRectF(13 * unit, 8 * unit, 6 * unit, 11 * unit)
    path = QPainterPath()
    path.addRoundedRect(capsule, 3 * unit, 3 * unit)
    painter.drawPath(path)

    pen = QPen(color)
    pen.setWidthF(1.6 * unit)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawArc(QRectF(10 * unit, 12 * unit, 12 * unit, 11 * unit), 0, -180 * 16)
    painter.drawLine(
        int(16 * unit), int(23 * unit), int(16 * unit), int(26 * unit)
    )


def _draw_slash(painter: QPainter, size: int, color: QColor) -> None:
    unit = size / 32.0
    pen = QPen(color)
    pen.setWidthF(2.4 * unit)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawLine(int(7 * unit), int(7 * unit), int(25 * unit), int(25 * unit))


def clear_cache() -> None:
    """Нужно при смене темы оформления."""
    _ICON_CACHE.clear()
