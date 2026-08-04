"""Общая основа вкладок настроек.

Вкладка отвечает только за перенос значений между виджетами и объектом
:class:`~voiceflow.core.settings.schema.Settings`. Чтением файла, проверкой
значений и сбросом занимается :class:`SettingsStore` — окно лишь вызывает его.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from voiceflow.core.settings.schema import Settings


class SettingsTab(QWidget):
    """Базовая вкладка."""

    #: Разделы настроек, которые очищает кнопка «Сбросить раздел».
    #: Пусто — вкладка не хранит настроек (например, «Инструкции»).
    sections: tuple[str, ...] = ()

    reset_requested = Signal()

    def load_from(self, settings: Settings) -> None:
        """Показывает текущие значения. Вызывается при каждом открытии окна."""

    def apply_to(self, settings: Settings) -> None:
        """Переносит значения из виджетов в настройки. Файл пишет окно."""

    def add_reset_row(self, layout: QVBoxLayout) -> None:
        """Добавляет кнопку сброса раздела в правый нижний угол вкладки."""
        if not self.sections:
            return
        row = QHBoxLayout()
        row.addStretch(1)
        button = QPushButton("Сбросить раздел")
        button.setToolTip(
            "Удаляет пользовательские значения раздела и возвращает заводские"
        )
        button.clicked.connect(self.reset_requested.emit)
        row.addWidget(button)
        layout.addLayout(row)
