"""Иконки рисуются кодом, а не хранятся файлами.

Так в репозиторий не попадают бинарные ресурсы, иконка автоматически
подстраивается под масштаб экрана и всегда соответствует цвету состояния.
Для панели задач и установщика дополнительно есть файл ``assets/voiceflow.ico``.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from voiceflow.core.state import AppState
from voiceflow.ui import theme

_ICON_CACHE: dict[tuple[AppState, int], QIcon] = {}
_APP_ICON: QIcon | None = None

#: Фирменный цвет значка приложения (не привязан к состоянию на плашке).
APP_ICON_COLOR = QColor("#1F6FEB")


def app_icon() -> QIcon:
    """Значок приложения для окна настроек, панели задач и exe.

    Сначала пробуем файл ``assets/voiceflow.ico`` (вшитый в сборку), иначе
    рисуем тот же силуэт программно — чтобы в разработке без сборки тоже
    была нормальная иконка, а не стандартный Python.
    """
    global _APP_ICON
    if _APP_ICON is not None:
        return _APP_ICON

    for candidate in _icon_file_candidates():
        if candidate.is_file():
            icon = QIcon(str(candidate))
            if not icon.isNull():
                _APP_ICON = icon
                return icon

    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(_paint_brand(size))
    _APP_ICON = icon
    return icon


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

    _draw_microphone(painter, size, QColor("#ffffff"), offset_x=0)

    if state is AppState.PAUSED:
        _draw_slash(painter, size, QColor("#ffffff"))

    painter.end()

    icon = QIcon(pixmap)
    _ICON_CACHE[cache_key] = icon
    return icon


def _icon_file_candidates() -> list[Path]:
    """Где искать файл иконки: рядом с пакетом, в сборке и в корне репозитория."""
    here = Path(__file__).resolve()
    roots = [
        here.parents[3] / "assets",  # src/voiceflow/ui → корень репо
        here.parents[2] / "assets",  # на всякий случай
        Path.cwd() / "assets",
    ]
    # PyInstaller: данные лежат во временной/_MEIPASS или рядом с exe.
    import sys

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.insert(0, Path(meipass) / "assets")
    if getattr(sys, "frozen", False):
        roots.insert(0, Path(sys.executable).resolve().parent / "assets")

    seen: set[Path] = set()
    result: list[Path] = []
    for root in roots:
        path = root / "voiceflow.ico"
        if path in seen:
            continue
        seen.add(path)
        result.append(path)
    return result


def _paint_brand(size: int) -> QPixmap:
    """Синий круг с микрофоном и лёгкой «волной» — узнаваемый значок VoiceFlow."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(APP_ICON_COLOR))
    painter.drawEllipse(QRectF(1, 1, size - 2, size - 2))

    # Внутренний блик — чуть объёма на маленьких размерах.
    highlight = QColor("#4C8DFF")
    painter.setBrush(QBrush(highlight))
    inset = size * 0.12
    painter.drawEllipse(QRectF(inset, inset * 0.7, size * 0.45, size * 0.35))

    _draw_microphone(painter, size, QColor("#ffffff"), offset_x=-2)
    _draw_flow_arcs(painter, size, QColor("#ffffff"))

    painter.end()
    return pixmap


def _draw_flow_arcs(painter: QPainter, size: int, color: QColor) -> None:
    """Две короткие дуги справа от микрофона — «поток» / flow."""
    unit = size / 32.0
    pen = QPen(color)
    pen.setWidthF(1.4 * unit)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawArc(QRectF(18 * unit, 10 * unit, 8 * unit, 10 * unit), -60 * 16, 120 * 16)
    painter.drawArc(QRectF(21 * unit, 11 * unit, 6 * unit, 8 * unit), -60 * 16, 120 * 16)


def _draw_microphone(
    painter: QPainter, size: int, color: QColor, *, offset_x: float = 0
) -> None:
    unit = size / 32.0
    shift = offset_x * unit
    painter.setBrush(QBrush(color))
    painter.setPen(Qt.PenStyle.NoPen)

    capsule = QRectF(13 * unit + shift, 8 * unit, 6 * unit, 11 * unit)
    path = QPainterPath()
    path.addRoundedRect(capsule, 3 * unit, 3 * unit)
    painter.drawPath(path)

    pen = QPen(color)
    pen.setWidthF(1.6 * unit)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawArc(
        QRectF(10 * unit + shift, 12 * unit, 12 * unit, 11 * unit), 0, -180 * 16
    )
    painter.drawLine(
        int(16 * unit + shift), int(23 * unit), int(16 * unit + shift), int(26 * unit)
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
    global _APP_ICON
    _ICON_CACHE.clear()
    _APP_ICON = None
