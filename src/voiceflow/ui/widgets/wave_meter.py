"""Бегущая волна уровня микрофона.

Почему волна, а не полоска: уровень приходит блоками примерно тридцать раз в
секунду, и полоска, которая каждый раз прыгала прямо к новому значению,
дёргалась. Здесь значение не подставляется, а притягивается к цели небольшими
шагами на своей частоте кадров, поэтому движение остаётся плавным даже при
неровном потоке данных.

Виджет получает готовые числа 0..1 и ничего не знает про аудио. Если данные
перестали приходить, волна сама успокаивается до тонкой линии — так она не
замирает на середине при закрытии микрофона.
"""

from __future__ import annotations

from collections import deque

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from voiceflow.ui import theme

#: Частота кадров волны. Тридцать кадров хватает для плавности и не греет
#: процессор: плашка живёт поверх всех окон постоянно.
FRAME_MS = 33

#: Сколько точек укладывается в волну по ширине.
POINTS = 44

#: Доля пути до цели за один кадр. Меньше — плавнее, но вяло.
SMOOTHING = 0.35

#: Затухание цели за кадр, когда новых данных нет.
TARGET_DECAY = 0.90

#: Ниже этого значения волна считается успокоившейся.
QUIET = 0.005

#: Показатель кривой отображения. Волна показывает наличие речи, а не громкость
#: в цифрах, а на тихом микрофоне линейная шкала оставляет её почти плоской.
DISPLAY_CURVE = 0.6

#: Виды индикатора. Разница только в отрисовке: сглаживание общее, поэтому
#: любой вид одинаково плавный.
STYLES: tuple[str, ...] = ("wave", "bars", "pulse")

#: Сколько столбиков рисовать в режиме эквалайзера.
BAR_COUNT = 16


class WaveMeter(QWidget):
    """Симметричная волна, бегущая справа налево."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._target = 0.0
        self._value = 0.0
        self._style = "wave"
        self._history: deque[float] = deque([0.0] * POINTS, maxlen=POINTS)

        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._advance)

    # ------------------------------------------------------------------ #
    # Данные
    # ------------------------------------------------------------------ #

    def set_level(self, rms: float, peak: float) -> None:
        """Принимает уровень. Пик подмешивается, чтобы всплески были заметны."""
        self._target = _shape(_clamp(max(rms, peak * 0.7)))
        if not self._timer.isActive():
            self._timer.start()

    def reset(self) -> None:
        """Возвращает волну к покою немедленно: микрофон закрыт."""
        self._target = 0.0
        self._value = 0.0
        self._history = deque([0.0] * POINTS, maxlen=POINTS)
        self._timer.stop()
        self.update()

    @property
    def amplitudes(self) -> tuple[float, ...]:
        """Текущая волна. Открыто для тестов, рисование их не касается."""
        return tuple(self._history)

    def _advance(self) -> None:
        """Один кадр: значение подтягивается к цели, история сдвигается."""
        self._value += (self._target - self._value) * SMOOTHING
        self._history.append(self._value)

        # Цель гаснет сама: если поток уровней прервался, волна успокоится,
        # а не останется стоять на середине.
        self._target *= TARGET_DECAY

        if self._value < QUIET and self._target < QUIET and not any(
            amplitude > QUIET for amplitude in self._history
        ):
            self._value = 0.0
            self._target = 0.0
            self._timer.stop()
        self.update()

    # ------------------------------------------------------------------ #
    # Отрисовка
    # ------------------------------------------------------------------ #

    def set_style(self, style: str) -> None:
        """Меняет вид индикатора: волна, столбики или пульс."""
        self._style = style if style in STYLES else "wave"
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 — имя из Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        area = QRectF(self.rect())
        center = area.center().y()

        if not any(amplitude > QUIET for amplitude in self._history):
            self._draw_resting_line(painter, area, center)
            painter.end()
            return

        if self._style == "bars":
            self._draw_bars(painter, area, center)
            painter.end()
            return
        if self._style == "pulse":
            self._draw_pulse(painter, area, center)
            painter.end()
            return

        top = self._edge(area, center, upward=True)
        bottom = self._edge(area, center, upward=False)

        path = _smooth_path(top)
        # Обратный путь по нижнему краю замыкает фигуру в цельную волну.
        back = _smooth_path(list(reversed(bottom)))
        path.connectPath(back)
        path.closeSubpath()

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(theme.METER_FILL)))
        painter.drawPath(path)
        painter.end()

    def _draw_bars(self, painter: QPainter, area: QRectF, center: float) -> None:
        """Столбики: привычный вид эквалайзера, читается на самом малом размере."""
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(theme.METER_FILL)))

        count = min(BAR_COUNT, len(self._history))
        step = area.width() / count
        width = max(2.0, step * 0.55)
        limit = area.height() / 2.0 - 0.5
        # Берём последние значения: столбики показывают недавнее, а не всю ленту.
        values = list(self._history)[-count:]

        for index, amplitude in enumerate(values):
            height = max(1.5, amplitude * limit)
            left = area.left() + index * step + (step - width) / 2.0
            bar = QRectF(left, center - height, width, height * 2)
            radius = width / 2.0
            painter.drawRoundedRect(bar, radius, radius)

    def _draw_pulse(self, painter: QPainter, area: QRectF, center: float) -> None:
        """Пульс: одна точка, которая дышит в такт голосу."""
        painter.setPen(Qt.PenStyle.NoPen)
        amplitude = self._history[-1] if self._history else 0.0
        limit = area.height() / 2.0

        # Ореол вокруг точки делает дыхание заметным, не увеличивая плашку.
        halo = QColor(theme.METER_FILL)
        halo.setAlpha(70)
        painter.setBrush(QBrush(halo))
        outer = max(2.0, limit * (0.45 + 0.55 * amplitude))
        painter.drawEllipse(QPointF(area.center().x(), center), outer, outer)

        painter.setBrush(QBrush(QColor(theme.METER_FILL)))
        inner = max(1.5, limit * (0.22 + 0.28 * amplitude))
        painter.drawEllipse(QPointF(area.center().x(), center), inner, inner)

    def _edge(self, area: QRectF, center: float, upward: bool) -> list[QPointF]:
        """Точки одного края волны."""
        count = len(self._history)
        step = area.width() / max(1, count - 1)
        # Половина высоты минус запас, чтобы сглаженная кривая не срезалась.
        limit = area.height() / 2.0 - 0.5
        sign = -1.0 if upward else 1.0

        points: list[QPointF] = []
        for index, amplitude in enumerate(self._history):
            # Края приглушаются, иначе волна выглядит обрубленной по бокам.
            taper = _taper(index, count)
            offset = amplitude * limit * taper
            # Тонкая линия по центру видна и на тишине.
            offset = max(offset, 0.5)
            points.append(QPointF(area.left() + index * step, center + sign * offset))
        return points

    @staticmethod
    def _draw_resting_line(painter: QPainter, area: QRectF, center: float) -> None:
        painter.setPen(QPen(QColor(theme.METER_BACKGROUND), 1.6, Qt.PenStyle.SolidLine))
        painter.drawLine(QPointF(area.left(), center), QPointF(area.right(), center))


def _smooth_path(points: list[QPointF]) -> QPainterPath:
    """Кривая через точки без углов: по середине каждой пары ставится узел."""
    path = QPainterPath()
    if not points:
        return path

    path.moveTo(points[0])
    for index in range(1, len(points)):
        previous = points[index - 1]
        current = points[index]
        middle = QPointF((previous.x() + current.x()) / 2.0, (previous.y() + current.y()) / 2.0)
        path.quadTo(previous, middle)
    path.lineTo(points[-1])
    return path


def _taper(index: int, count: int) -> float:
    """Множитель, сводящий амплитуду к нулю у левого и правого края."""
    if count < 2:
        return 1.0
    position = index / (count - 1)
    # Мягкая трапеция: середина в полную силу, края в четверть.
    return 0.25 + 0.75 * min(1.0, min(position, 1.0 - position) * 4.0)


def _shape(value: float) -> float:
    """Поднимает тихие уровни, не задирая громкие к потолку."""
    if value <= 0.0:
        return 0.0
    return value**DISPLAY_CURVE


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))
