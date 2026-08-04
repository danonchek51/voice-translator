"""Плавающая плашка состояния.

Три обязательных свойства:

* не забирает фокус у активного приложения — иначе диктовка прямо в редактор
  теряет смысл;
* не появляется на панели задач;
* переживает перезапуск и отключение монитора, на котором стояла.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from voiceflow.core.settings.schema import OverlaySettings
from voiceflow.core.state import AppState
from voiceflow.platform.base import get_window_styler
from voiceflow.ui import theme
from voiceflow.ui.geometry import Placement, ScreenRect, clamp_to_screen, resolve_placement
from voiceflow.ui.widgets.level_meter import LevelMeter

logger = logging.getLogger(__name__)

#: Смещение мыши, начиная с которого нажатие считается перетаскиванием.
DRAG_THRESHOLD_PX = 6


def available_screens() -> list[ScreenRect]:
    """Доступные области всех мониторов без панели задач."""
    app = QApplication.instance()
    if app is None:
        return []
    primary = QApplication.primaryScreen()
    rects: list[ScreenRect] = []
    for screen in QApplication.screens():
        geometry = screen.availableGeometry()
        rects.append(
            ScreenRect(
                name=screen.name(),
                x=geometry.x(),
                y=geometry.y(),
                width=geometry.width(),
                height=geometry.height(),
                is_primary=screen is primary,
            )
        )
    return rects


class OverlayWindow(QWidget):
    """Небольшое окно поверх остальных с состоянием и уровнем микрофона."""

    #: Щелчок по плашке (не перетаскивание).
    clicked = Signal()
    #: Правый щелчок: показать меню в переданной глобальной точке.
    context_menu_requested = Signal(QPoint)
    #: Новое положение: x, y, имя монитора.
    position_changed = Signal(int, int, str)

    def __init__(self, settings: OverlaySettings) -> None:
        super().__init__(None)
        # Имя нужно листу стилей: плашка исключается из общего тёмного фона,
        # потому что рисует себя сама.
        self.setObjectName("overlay")
        self._state = AppState.IDLE
        self._detail = ""
        self._timer_text = ""
        self._scale = settings.scale
        self._screen_name = settings.screen_id
        self._styler = get_window_styler()
        self._styled = False

        self._drag_origin: QPoint | None = None
        self._window_origin: QPoint | None = None
        self._dragged = False

        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

        self._label = QLabel(self)
        self._label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._label.setStyleSheet(f"color: {theme.TEXT}; background: transparent;")
        self._label.setObjectName("overlayLabel")

        self._meter = LevelMeter(self)

        layout = QVBoxLayout(self)
        layout.addWidget(self._label)
        layout.addWidget(self._meter)
        self.setLayout(layout)

        self.apply_settings(settings)
        self._refresh_label()

    # ------------------------------------------------------------------ #
    # Настройки и положение
    # ------------------------------------------------------------------ #

    def apply_settings(self, settings: OverlaySettings) -> None:
        """Применяет масштаб, прозрачность, признак «поверх всех окон»."""
        self._scale = settings.scale
        self._apply_scale()

        self.setWindowOpacity(max(0.3, min(1.0, settings.opacity / 100.0)))

        flags = self.windowFlags()
        if settings.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        if flags != self.windowFlags():
            was_visible = self.isVisible()
            self.setWindowFlags(flags)
            self._styled = False
            if was_visible:
                self.show_without_focus()

        self.restore_position(settings)

    def _apply_scale(self) -> None:
        width = theme.scaled(theme.BASE_WIDTH, self._scale)
        height = theme.scaled(theme.BASE_HEIGHT, self._scale)
        self.setFixedSize(width, height)

        dot_area = theme.scaled(26, self._scale)
        margin = theme.scaled(8, self._scale)
        layout = self.layout()
        if layout is not None:
            right_margin = margin + theme.scaled(4, self._scale)
            layout.setContentsMargins(dot_area, margin, right_margin, margin)
            layout.setSpacing(theme.scaled(3, self._scale))

        font = QFont(self._label.font())
        font.setPointSizeF(theme.BASE_FONT_PT * self._scale / 100.0)
        self._label.setFont(font)
        self._label.setFixedHeight(theme.scaled(16, self._scale))
        self._meter.setFixedHeight(theme.scaled(5, self._scale))

    def restore_position(self, settings: OverlaySettings) -> None:
        """Возвращает плашку туда, где она была, с проверкой на мониторы."""
        placement = resolve_placement(
            screens=available_screens(),
            width=self.width(),
            height=self.height(),
            saved_x=settings.x,
            saved_y=settings.y,
            saved_screen=settings.screen_id,
        )
        self._move_to(placement)
        if placement.adjusted:
            logger.info(
                "Положение плашки скорректировано под текущие мониторы: %s, %s",
                placement.x,
                placement.y,
            )
            self.position_changed.emit(placement.x, placement.y, placement.screen_name)

    def _move_to(self, placement: Placement) -> None:
        self._screen_name = placement.screen_name
        self.move(placement.x, placement.y)

    # ------------------------------------------------------------------ #
    # Состояние
    # ------------------------------------------------------------------ #

    def set_state(self, state: AppState, detail: str = "") -> None:
        self._state = state
        self._detail = detail
        if state is not AppState.RECORDING:
            self._timer_text = ""
        if state in (AppState.IDLE, AppState.PAUSED, AppState.ERROR):
            self._meter.reset()
        self._refresh_label()
        self.update()

    def set_timer_seconds(self, seconds: float) -> None:
        """Показывает длительность текущей записи."""
        if self._state is not AppState.RECORDING:
            return
        total = int(seconds)
        self._timer_text = f"{total // 60}:{total % 60:02d}"
        self._refresh_label()

    def set_level(self, rms: float, peak: float) -> None:
        self._meter.set_level(rms, peak)

    def _refresh_label(self) -> None:
        style = theme.style_for(self._state)
        if self._state is AppState.PROCESSING and self._detail:
            # Для обработки в пояснении приходит режим: показываем «Перевожу».
            parts = [theme.processing_label(self._detail)]
        else:
            parts = [style.label]
            if self._timer_text:
                parts.append(self._timer_text)
            elif self._detail:
                parts.append(self._detail)
        text = "  ".join(parts)
        self._label.setText(text)
        self.setToolTip(f"VoiceFlow — {text}")

    # ------------------------------------------------------------------ #
    # Показ без кражи фокуса
    # ------------------------------------------------------------------ #

    def show_without_focus(self) -> None:
        """Показывает плашку, не отбирая фокус у активного приложения."""
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.show()
        self._apply_platform_style()

    def _apply_platform_style(self) -> None:
        if self._styled:
            return
        handle = int(self.winId())
        if not handle:
            return
        # Флагов Qt на Windows недостаточно: без WS_EX_NOACTIVATE щелчок по
        # плашке всё равно переводит на неё фокус.
        self._styler.make_non_activating(handle)
        self._styler.exclude_from_taskbar(handle)
        self._styled = True

    # ------------------------------------------------------------------ #
    # Перетаскивание
    # ------------------------------------------------------------------ #

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - имя из Qt
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.globalPosition().toPoint()
            self._window_origin = self.pos()
            self._dragged = False
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - имя из Qt
        if self._drag_origin is None or self._window_origin is None:
            super().mouseMoveEvent(event)
            return

        delta = event.globalPosition().toPoint() - self._drag_origin
        if not self._dragged and delta.manhattanLength() < DRAG_THRESHOLD_PX:
            event.accept()
            return

        self._dragged = True
        self.move(self._window_origin + delta)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - имя из Qt
        if event.button() != Qt.MouseButton.LeftButton or self._drag_origin is None:
            super().mouseReleaseEvent(event)
            return

        self.setCursor(Qt.CursorShape.OpenHandCursor)
        dragged = self._dragged
        self._drag_origin = None
        self._window_origin = None
        self._dragged = False
        event.accept()

        if dragged:
            self._commit_position()
        else:
            self.clicked.emit()

    def contextMenuEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        self.context_menu_requested.emit(event.globalPos())
        event.accept()

    def _commit_position(self) -> None:
        """Прижимает плашку к границам монитора и сохраняет положение."""
        screens = available_screens()
        position = self.pos()
        x, y = position.x(), position.y()
        name = self._screen_name

        current = self.screen()
        if current is not None:
            name = current.name()
            geometry = current.availableGeometry()
            rect = ScreenRect(
                name=name,
                x=geometry.x(),
                y=geometry.y(),
                width=geometry.width(),
                height=geometry.height(),
            )
            x, y = clamp_to_screen(rect, x, y, self.width(), self.height())
        elif screens:
            x, y = clamp_to_screen(screens[0], x, y, self.width(), self.height())
            name = screens[0].name

        if (x, y) != (position.x(), position.y()):
            self.move(x, y)
        self._screen_name = name
        self.position_changed.emit(x, y, name)

    # ------------------------------------------------------------------ #
    # Отрисовка
    # ------------------------------------------------------------------ #

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - имя из Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        radius = theme.scaled(theme.BASE_RADIUS, self._scale)
        area = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        painter.setBrush(QBrush(QColor(theme.BACKGROUND)))
        painter.setPen(QPen(QColor(theme.BORDER), 1))
        painter.drawRoundedRect(area, radius, radius)

        dot_size = theme.scaled(10, self._scale)
        dot_x = theme.scaled(9, self._scale)
        dot_y = (self.height() - dot_size) / 2.0
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(theme.style_for(self._state).color)))
        painter.drawEllipse(QRectF(dot_x, dot_y, dot_size, dot_size))

        painter.end()
