"""Подпись, которая укорачивается многоточием, а не обрезается.

Обычная ``QLabel`` при нехватке места режет текст по границе виджета, и
последняя буква оказывается разрубленной пополам — именно так на плашке
появлялось «Активно д». Здесь текст сокращается по фактической ширине в
момент отрисовки: до этого момента Qt ещё не знает настоящих размеров, и
любое сокращение заранее срезает лишнее.

Полный текст всегда доступен через ``text()``: он нужен подсказке.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPaintEvent
from PySide6.QtWidgets import QLabel, QWidget


class ElidedLabel(QLabel):
    """Однострочная подпись с многоточием вместо обрезки."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setTextFormat(Qt.TextFormat.PlainText)

    @property
    def is_elided(self) -> bool:
        """Не поместился ли текст целиком. Нужно тестам и подсказкам."""
        metrics = self.fontMetrics()
        return metrics.horizontalAdvance(self.text()) > self.contentsRect().width()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 — имя из Qt
        painter = QPainter(self)
        metrics = painter.fontMetrics()
        area = self.contentsRect()
        elided = metrics.elidedText(self.text(), Qt.TextElideMode.ElideRight, area.width())
        painter.drawText(area, int(self.alignment()), elided)
        painter.end()
