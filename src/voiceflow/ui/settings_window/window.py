"""Окно настроек: восемь вкладок поверх существующих подсистем.

Окно ничего не считает само. Значения оно берёт из :class:`Settings`,
записывает через :class:`SettingsStore`, а действия — открыть мастер,
скопировать текст, вставить результат — отдаёт наружу сигналами: решает
их контроллер, у которого есть доступ к платформенному слою.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from voiceflow.core.history import HistoryRepository
from voiceflow.core.models import ModelManager
from voiceflow.core.settings.store import SettingsStore
from voiceflow.core.settings.transfer import (
    TransferError,
    export_settings,
    import_settings,
    inspect_bundle,
)
from voiceflow.core.text.modes import describe
from voiceflow.platform.base import Autostart
from voiceflow.ui import style
from voiceflow.ui.settings_window.common import SettingsTab
from voiceflow.ui.settings_window.tab_activation import ActivationTab
from voiceflow.ui.settings_window.tab_diagnostics import DiagnosticsTab
from voiceflow.ui.settings_window.tab_general import GeneralTab
from voiceflow.ui.settings_window.tab_history import HistoryTab
from voiceflow.ui.settings_window.tab_models import ModelsTab
from voiceflow.ui.settings_window.tab_processing import ProcessingTab
from voiceflow.ui.settings_window.tab_prompts import PromptsTab
from voiceflow.ui.settings_window.tab_recognition import RecognitionTab

logger = logging.getLogger(__name__)

#: Порядок вкладок из плана. Индексы нужны, чтобы открывать окно на нужной.
TAB_GENERAL = 0
TAB_ACTIVATION = 1
TAB_RECOGNITION = 2
TAB_PROCESSING = 3
TAB_PROMPTS = 4
TAB_MODELS = 5
TAB_HISTORY = 6
TAB_DIAGNOSTICS = 7

#: Окно не должно вырастать выше экрана: содержимое уходит в прокрутку.
MAX_HEIGHT_FRACTION = 0.85


def _scrollable(tab: SettingsTab) -> QScrollArea:
    """Оборачивает вкладку в прокрутку без рамки."""
    area = QScrollArea()
    area.setWidget(tab)
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return area


class SettingsWindow(QDialog):
    """Обычное окно: его закрытие не завершает приложение."""

    settings_saved = Signal()
    wizard_requested = Signal()
    listening_toggle_requested = Signal()
    copy_requested = Signal(str)
    paste_requested = Signal(str)

    def __init__(
        self,
        store: SettingsStore,
        models: ModelManager,
        history: HistoryRepository,
        *,
        context_provider=None,
        capture_provider=None,
        transcribers_provider=None,
        processor_provider=None,
        delivery_provider=None,
        autostart: Autostart | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store

        self.setWindowTitle("Настройки VoiceFlow")
        self.resize(900, 680)
        self._limit_height()

        self.general = GeneralTab(autostart)
        self.activation = ActivationTab()
        self.recognition = RecognitionTab(models, transcribers_provider)
        self.processing = ProcessingTab()
        self.prompts = PromptsTab(processor_provider=processor_provider)
        self.models = ModelsTab(models)
        self.history = HistoryTab(history)
        self.diagnostics = DiagnosticsTab(
            context_provider=context_provider,
            capture_provider=capture_provider,
            transcribers_provider=transcribers_provider,
            processor_provider=processor_provider,
            delivery_provider=delivery_provider,
        )

        self._tab_list: list[SettingsTab] = []
        self.tabs = QTabWidget()
        for tab, title in (
            (self.general, "Общие"),
            (self.activation, "Активация"),
            (self.recognition, "Распознавание"),
            (self.processing, "Обработка"),
            (self.prompts, "Инструкции"),
            (self.models, "Модели"),
            (self.history, "История"),
            (self.diagnostics, "Диагностика"),
        ):
            # Содержимое вкладок разной высоты. Без прокрутки окно вырастает
            # выше экрана, и кнопки внизу становятся недоступны.
            self.tabs.addTab(_scrollable(tab), title)
            self._tab_list.append(tab)
            tab.reset_requested.connect(lambda t=tab: self._reset_sections(t))

        root = QVBoxLayout(self)
        root.setContentsMargins(style.PADDING, style.PADDING, style.PADDING, style.PADDING)
        root.setSpacing(style.GAP)
        root.addWidget(self.tabs)

        buttons = QHBoxLayout()
        buttons.setSpacing(style.GAP)
        self.chain_hint = QLabel()
        self.chain_hint.setProperty("role", "hint")
        buttons.addWidget(self.chain_hint)
        buttons.addStretch(1)
        save_button = QPushButton("Сохранить")
        close_button = QPushButton("Закрыть")
        save_button.setDefault(True)
        save_button.clicked.connect(self.save)
        close_button.clicked.connect(self.close)
        buttons.addWidget(save_button)
        buttons.addWidget(close_button)
        root.addLayout(buttons)

        self.general.reset_all_requested.connect(self._reset_all)
        self.general.export_requested.connect(self._export_settings)
        self.general.import_requested.connect(self._import_settings)
        self.activation.listening_toggle_requested.connect(
            self.listening_toggle_requested.emit
        )
        self.models.wizard_requested.connect(self.wizard_requested.emit)
        self.history.copy_requested.connect(self.copy_requested.emit)
        self.history.paste_requested.connect(self.paste_requested.emit)

        self.reload()

    # ------------------------------------------------------------------ #
    # Загрузка и сохранение
    # ------------------------------------------------------------------ #

    def _tabs(self) -> list[SettingsTab]:
        return list(self._tab_list)

    def reload(self) -> None:
        """Показывает актуальные значения во всех вкладках."""
        settings = self._store.settings
        for tab in self._tabs():
            tab.load_from(settings)
        self.chain_hint.setText(f"Обработка: {describe(settings.processing)}")

    def save(self) -> None:
        """Собирает значения со всех вкладок и записывает отличия в файл."""
        settings = self._store.settings
        for tab in self._tabs():
            tab.apply_to(settings)

        notes = self._store.save(settings)
        # Настройки чинят сами себя, поэтому после записи показываем то,
        # что действительно сохранилось.
        self.reload()

        if notes:
            QMessageBox.warning(self, "Настройки", "\n".join(notes))
        self.settings_saved.emit()

    def _reset_sections(self, tab: SettingsTab) -> None:
        if not tab.sections:
            return
        names = ", ".join(tab.sections)
        answer = QMessageBox.question(
            self,
            "Сброс раздела",
            f"Вернуть заводские значения для раздела: {names}?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        for section in tab.sections:
            self._store.reset_section(section)
        self.reload()
        self.settings_saved.emit()

    def _reset_all(self) -> None:
        answer = QMessageBox.question(
            self,
            "Сброс всех настроек",
            "Вернуть заводские значения для всех разделов? "
            "Инструкции и словарь замен это не затронет.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._store.reset_all()
        self.reload()
        self.settings_saved.emit()

    # ------------------------------------------------------------------ #
    # Перенос настроек
    # ------------------------------------------------------------------ #

    def _export_settings(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт настроек", "voiceflow-settings.zip", "Архив (*.zip)"
        )
        if not path:
            return

        include_history = (
            QMessageBox.question(
                self,
                "Экспорт настроек",
                "Добавить в архив историю результатов? "
                "Она содержит распознанные тексты.",
            )
            == QMessageBox.StandardButton.Yes
        )

        # Настройки пишутся в файл перед упаковкой, иначе уедет прежняя версия.
        self.save()
        try:
            result = export_settings(Path(path), include_history=include_history)
        except OSError as exc:
            QMessageBox.warning(self, "Экспорт настроек", str(exc))
            return

        message = "Сохранено: " + ", ".join(result.items)
        if result.notes:
            message += "\n\n" + "\n".join(result.notes)
        QMessageBox.information(self, "Экспорт настроек", message)

    def _import_settings(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Импорт настроек", "", "Архив (*.zip)"
        )
        if not path:
            return

        try:
            info = inspect_bundle(Path(path))
        except TransferError as exc:
            QMessageBox.warning(self, "Импорт настроек", str(exc))
            return

        answer = QMessageBox.question(
            self,
            "Импорт настроек",
            f"Архив от {info.created_at}, версия {info.app_version}.\n"
            f"Внутри: {info.describe()}.\n\n"
            "Текущие настройки будут заменены. Продолжить?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        include_history = info.has_history and (
            QMessageBox.question(
                self, "Импорт настроек", "Заменить историю данными из архива?"
            )
            == QMessageBox.StandardButton.Yes
        )

        try:
            result = import_settings(Path(path), include_history=include_history)
        except (TransferError, OSError) as exc:
            QMessageBox.warning(self, "Импорт настроек", str(exc))
            return

        # Перечитываем файл: миграцию схемы выполняет store, а не архив.
        self._store.load()
        self.reload()
        self.settings_saved.emit()

        message = "Импортировано: " + (", ".join(result.items) or "пусто")
        notes = result.notes + self._store.notes
        if notes:
            message += "\n\n" + "\n".join(notes)
        QMessageBox.information(self, "Импорт настроек", message)

    # ------------------------------------------------------------------ #
    # Открытие на нужной вкладке
    # ------------------------------------------------------------------ #

    def open_at(self, index: int) -> None:
        """Показывает окно на указанной вкладке и обновляет её данные."""
        self.tabs.setCurrentIndex(index)
        self.reload()
        self.show()
        self.raise_()
        self.activateWindow()

    def set_listening(self, listening: bool) -> None:
        self.activation.set_listening(listening)

    def _limit_height(self) -> None:
        """Не даёт окну вырасти выше рабочей области монитора."""
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        self.setMaximumHeight(int(available.height() * MAX_HEIGHT_FRACTION))
        self.setMaximumWidth(available.width())
