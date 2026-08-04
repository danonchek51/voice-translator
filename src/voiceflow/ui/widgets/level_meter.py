"""Полоска уровня микрофона.

Виджет получает уже посчитанное число 0..1 и ничего не знает про аудио.
Значение затухает само, если обновления перестали приходить: так полоска
не «зависает» на середине при закрытии микрофона.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QWidget

from voiceflow.ui import theme

#: Частота перерисовки при затухании.
DECAY_INTERVAL_MS = 60
DECAY_STEP = 0.08


class LevelMeter(QWidget):
    """Горизонтальная полоска с отметкой пикового значения."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rms = 0.0
        self._peak = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._decay = QTimer(self)
        self._decay.setInterval(DECAY_INTERVAL_MS)
        self._decay.timeout.connect(self._fade)

    def set_level(self, rms: float, peak: float) -> None:
        self._rms = _clamp(rms)
        self._peak = _clamp(peak)
        if not self._decay.isActive():
            self._decay.start()
        self.update()

    def reset(self) -> None:
        self._rms = 0.0
        self._peak = 0.0
        self._decay.stop()
        self.update()

    def _fade(self) -> None:
        """Плавно гасит полоску, если новые значения не приходят."""
        if self._rms <= 0.0 and self._peak <= 0.0:
            self._decay.stop()
            return
        self._rms = max(0.0, self._rms - DECAY_STEP)
        self._peak = max(0.0, self._peak - DECAY_STEP)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - имя из Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        area = QRectF(self.rect())
        radius = area.height() / 2.0

        painter.setBrush(QBrush(QColor(theme.METER_BACKGROUND)))
        painter.drawRoundedRect(area, radius, radius)

        if self._rms > 0.0:
            fill = QRectF(area)
            fill.setWidth(area.width() * self._rms)
            painter.setBrush(QBrush(QColor(theme.METER_FILL)))
            painter.drawRoundedRect(fill, radius, radius)

        if self._peak > 0.0:
            marker_width = max(2.0, area.height() / 4.0)
            marker_x = min(area.width() - marker_width, area.width() * self._peak)
            marker = QRectF(marker_x, area.top(), marker_width, area.height())
            painter.setBrush(QBrush(QColor(theme.METER_PEAK)))
            painter.drawRoundedRect(marker, marker_width / 2.0, marker_width / 2.0)

        painter.end()


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))
