"""Вкладка «Общие»."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from voiceflow.core.settings.schema import LOG_LEVELS, Settings
from voiceflow.platform.base import Autostart, get_autostart
from voiceflow.ui.settings_window.common import SettingsTab

UI_LANGUAGES = {"ru": "Русский", "en": "English"}


class GeneralTab(SettingsTab):
    sections = ("system",)

    reset_all_requested = Signal()
    export_requested = Signal()
    import_requested = Signal()

    def __init__(self, autostart: Autostart | None = None) -> None:
        super().__init__()
        self._autostart = autostart or get_autostart()

        layout = QVBoxLayout(self)

        startup = QGroupBox("Запуск")
        startup_form = QFormLayout(startup)
        self.autostart = QCheckBox("Запускать вместе с Windows")
        self.start_minimized = QCheckBox("Запускать свёрнутым в трей")
        startup_form.addRow(self.autostart)
        startup_form.addRow(self.start_minimized)

        if not self._autostart.is_supported:
            self.autostart.setEnabled(False)
            self.autostart.setToolTip(self._autostart.description)
            startup_form.addRow(QLabel(self._autostart.description))
        else:
            self.autostart.setToolTip(self._autostart.description)
        layout.addWidget(startup)

        interface = QGroupBox("Интерфейс и журнал")
        interface_form = QFormLayout(interface)
        self.ui_language = QComboBox()
        for code, title in UI_LANGUAGES.items():
            self.ui_language.addItem(title, code)
        self.log_level = QComboBox()
        self.log_level.addItems(list(LOG_LEVELS))
        self.log_user_text = QCheckBox("Записывать распознанный текст в журнал")
        self.log_user_text.setToolTip(
            "Только для отладки: обычно в журнал попадают лишь события и время"
        )
        interface_form.addRow("Язык интерфейса", self.ui_language)
        interface_form.addRow("Уровень журнала", self.log_level)
        interface_form.addRow(self.log_user_text)
        layout.addWidget(interface)

        transfer = QGroupBox("Перенос на другой компьютер")
        transfer_layout = QVBoxLayout(transfer)
        transfer_layout.addWidget(
            QLabel(
                "В архив попадают настройки, изменённые инструкции и словарь "
                "замен. Модели не переносятся — их загрузит мастер."
            )
        )
        transfer_buttons = QHBoxLayout()
        export_button = QPushButton("Экспортировать настройки…")
        import_button = QPushButton("Импортировать настройки…")
        export_button.clicked.connect(self.export_requested.emit)
        import_button.clicked.connect(self.import_requested.emit)
        transfer_buttons.addWidget(export_button)
        transfer_buttons.addWidget(import_button)
        transfer_buttons.addStretch(1)
        transfer_layout.addLayout(transfer_buttons)
        layout.addWidget(transfer)

        layout.addStretch(1)

        danger = QHBoxLayout()
        danger.addStretch(1)
        reset_all = QPushButton("Сбросить все настройки…")
        reset_all.clicked.connect(self.reset_all_requested.emit)
        danger.addWidget(reset_all)
        layout.addLayout(danger)

        self.add_reset_row(layout)

    def load_from(self, settings: Settings) -> None:
        system = settings.system
        # Истина об автозапуске — в системе, а не в файле настроек: пользователь
        # мог убрать запись вручную.
        self.autostart.setChecked(
            self._autostart.is_enabled() if self._autostart.is_supported else False
        )
        self.start_minimized.setChecked(system.start_minimized)
        index = self.ui_language.findData(system.ui_language)
        self.ui_language.setCurrentIndex(index if index >= 0 else 0)
        self.log_level.setCurrentText(system.log_level)
        self.log_user_text.setChecked(system.log_user_text)

    def apply_to(self, settings: Settings) -> None:
        system = settings.system
        system.start_minimized = self.start_minimized.isChecked()
        system.ui_language = str(self.ui_language.currentData())
        system.log_level = self.log_level.currentText()
        system.log_user_text = self.log_user_text.isChecked()

        wanted = self.autostart.isChecked()
        if self._autostart.is_supported and wanted != self._autostart.is_enabled():
            if self._autostart.set_enabled(wanted):
                system.autostart = wanted
            else:
                # Система отказала — настройка не должна врать пользователю.
                self.autostart.setChecked(self._autostart.is_enabled())
        else:
            system.autostart = wanted and self._autostart.is_supported
