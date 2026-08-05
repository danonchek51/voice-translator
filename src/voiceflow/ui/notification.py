"""Отдельное окно для сообщений, которые не помещаются на плашку.

Плашка шириной меньше двухсот точек: длинное сообщение об ошибке там
превращается в обрезанную строку, из которой ничего не понять. Такие
сообщения показываются здесь.

Окно намеренно не забирает фокус: человек диктует в другое приложение, и
украденный фокус ломает весь сценарий. Ошибка ждёт, пока её закроют,
уведомление уходит само.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from voiceflow.platform.base import get_window_styler

logger = logging.getLogger(__name__)

#: Сколько живёт уведомление, которое не требует решения.
NOTICE_SECONDS = 6

#: Отступ от края экрана.
MARGIN = 24

WIDTH = 380


class NotificationWindow(QWidget):
    """Небольшое окно с сообщением у края экрана."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("notification")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedWidth(WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(8)

        self._title = QLabel(self)
        self._title.setObjectName("notificationTitle")
        layout.addWidget(self._title)

        self._body = QLabel(self)
        self._body.setWordWrap(True)
        self._body.setObjectName("notificationBody")
        layout.addWidget(self._body)

        self._hint = QLabel(self)
        self._hint.setWordWrap(True)
        self._hint.setProperty("role", "hint")
        layout.addWidget(self._hint)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._close_button = QPushButton("Понятно", self)
        self._close_button.clicked.connect(self.hide)
        buttons.addWidget(self._close_button)
        layout.addLayout(buttons)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

        self._styled = False

    # ------------------------------------------------------------------ #
    # Показ
    # ------------------------------------------------------------------ #

    def show_error(self, message: str, hint: str = "") -> None:
        """Ошибка ждёт, пока её прочитают: сама не исчезает."""
        self._show("Не получилось", message, hint, seconds=0, error=True)

    def show_notice(self, message: str, hint: str = "") -> None:
        """Уведомление уходит само."""
        self._show("VoiceFlow", message, hint, seconds=NOTICE_SECONDS, error=False)

    def _show(
        self, title: str, message: str, hint: str, seconds: int, error: bool
    ) -> None:
        self._title.setText(title)
        self._title.setProperty("state", "error" if error else "notice")
        self._body.setText(message)
        self._hint.setText(hint)
        self._hint.setVisible(bool(hint))

        # Смена свойства не перерисовывает виджет сама.
        style = self._title.style()
        style.unpolish(self._title)
        style.polish(self._title)

        self.adjustSize()
        self._move_to_corner()
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.show()
        self.raise_()
        self._apply_platform_style()

        self._timer.stop()
        if seconds > 0:
            self._timer.start(seconds * 1000)

    def _move_to_corner(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(
            area.right() - self.width() - MARGIN,
            area.top() + MARGIN,
        )

    def _apply_platform_style(self) -> None:
        if self._styled:
            return
        handle = int(self.winId())
        if not handle:
            return
        # Без этого щелчок по окну уводит фокус из приложения, куда диктуют.
        styler = get_window_styler()
        styler.make_non_activating(handle)
        styler.exclude_from_taskbar(handle)
        self._styled = True
