"""Общая основа вкладок настроек.

Вкладка отвечает только за перенос значений между виджетами и объектом
:class:`~voiceflow.core.settings.schema.Settings`. Чтением файла, проверкой
значений и сбросом занимается :class:`SettingsStore` — окно лишь вызывает его.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from voiceflow.core.settings.schema import Settings


class SettingsTab(QWidget):
    """Базовая вкладка."""

    #: Разделы настроек, которые очищает кнопка «Сбросить раздел».
    #: Пусто — вкладка не хранит настроек (например, «Инструкции»).
    sections: tuple[str, ...] = ()

    #: Подсказки полей вкладки: имя атрибута -> текст. Берутся из
    #: :mod:`voiceflow.ui.hints`, где собраны все объяснения разом.
    hints: ClassVar[Mapping[str, str]] = {}

    reset_requested = Signal()

    def hint_targets(self) -> dict[str, QWidget]:
        """Поля, которые лежат не в атрибутах, а в словарях вкладки."""
        return {}

    def apply_hints(self) -> list[str]:
        """Расставляет подсказки по полям вкладки.

        Возвращает имена полей, для которых подсказки не нашлось: тест по
        этому списку следит, что новая настройка не осталась без объяснения.
        """
        extra = self.hint_targets()
        missing: list[str] = []
        for name, text in self.hints.items():
            widget = getattr(self, name, None) or extra.get(name)
            if widget is None:
                missing.append(name)
                continue
            widget.setToolTip(text)
        return missing

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
