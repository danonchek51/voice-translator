"""Вкладка «Модели».

Своей логики загрузки здесь нет: всё берётся у менеджера моделей этапа 9,
а сама загрузка выполняется мастером первого запуска.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from voiceflow.core.models import ModelManager, get_preset
from voiceflow.core.settings.schema import Settings
from voiceflow.ui.formatting import human_size
from voiceflow.ui.settings_window.common import SettingsTab

logger = logging.getLogger(__name__)

#: Начиная с этого объёма загрузка считается большой и требует подтверждения.
LARGE_DOWNLOAD_BYTES = 2 * 1024**3


class ModelsTab(SettingsTab):
    # Пресет живёт в разделе recognition и меняется на своей вкладке.
    sections = ()

    wizard_requested = Signal()

    def __init__(self, models: ModelManager) -> None:
        super().__init__()
        self._models = models
        self._preset = "standard"

        layout = QVBoxLayout(self)

        self.preset_label = QLabel()
        self.preset_label.setWordWrap(True)
        layout.addWidget(self.preset_label)

        box = QGroupBox("Состав пресета")
        box_layout = QVBoxLayout(box)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Модель", "Назначение", "Состояние", "Размер"])
        self.tree.setRootIsDecorated(False)
        box_layout.addWidget(self.tree)
        layout.addWidget(box, stretch=1)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        buttons = QHBoxLayout()
        self.wizard_button = QPushButton("Открыть мастер загрузки…")
        self.wizard_button.clicked.connect(self._request_wizard)
        self.folder_button = QPushButton("Взять из готовой папки…")
        self.folder_button.clicked.connect(self._import_from_folder)
        self.refresh_button = QPushButton("Обновить")
        self.refresh_button.clicked.connect(self.reload)
        buttons.addWidget(self.wizard_button)
        buttons.addWidget(self.folder_button)
        buttons.addStretch(1)
        buttons.addWidget(self.refresh_button)
        layout.addLayout(buttons)

    # ------------------------------------------------------------------ #
    # Отображение
    # ------------------------------------------------------------------ #

    def load_from(self, settings: Settings) -> None:
        self._preset = settings.recognition.preset
        self.reload()

    def reload(self) -> None:
        spec = get_preset(self._preset)
        plan = self._models.download_plan(self._preset)

        self.preset_label.setText(
            f"Пресет «{spec.title}». {spec.summary}\n"
            f"Требования: {spec.requirements}. На диске занято "
            f"{human_size(self._models.disk_usage())}."
        )

        self.tree.clear()
        for model in plan.installed:
            self._add_row(model, "установлена")
        for model in plan.missing:
            self._add_row(model, "не загружена")
        for model in plan.manual:
            self._add_row(model, "ставится вручную")
        for column in range(4):
            self.tree.resizeColumnToContents(column)

        if plan.missing:
            self.summary.setText(
                f"К загрузке {len(plan.missing)} шт., примерно "
                f"{human_size(plan.total_bytes)}. Загрузка идёт в мастере "
                "и продолжается с прерванного места."
            )
        elif plan.manual:
            self.summary.setText(
                "Автоматически загружать нечего. Осталось поставить вручную "
                "то, что отмечено в списке."
            )
        else:
            self.summary.setText("Все модели пресета на месте.")

    def _add_row(self, model, state: str) -> None:  # type: ignore[no-untyped-def]
        status = self._models.status(model.id)
        size = (
            human_size(status.size_on_disk)
            if status is not None and status.installed and status.size_on_disk
            else human_size(model.size_bytes)
        )
        item = QTreeWidgetItem([model.title, model.purpose, state, size])
        if model.notes:
            item.setToolTip(0, model.notes)
        self.tree.addTopLevelItem(item)

    # ------------------------------------------------------------------ #
    # Действия
    # ------------------------------------------------------------------ #

    def _request_wizard(self) -> None:
        plan = self._models.download_plan(self._preset)
        if plan.total_bytes >= LARGE_DOWNLOAD_BYTES:
            answer = QMessageBox.question(
                self,
                "Большая загрузка",
                f"Предстоит скачать примерно {human_size(plan.total_bytes)}. "
                "Это займёт время и место на диске. Продолжить?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.wizard_requested.emit()

    def _import_from_folder(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Папка с готовыми моделями")
        if not directory:
            return
        try:
            imported = self._models.import_from_folder(self._preset, Path(directory))
        except OSError as exc:
            QMessageBox.warning(self, "Импорт моделей", str(exc))
            return

        if imported:
            QMessageBox.information(
                self, "Импорт моделей", "Взято из папки: " + ", ".join(imported)
            )
        else:
            QMessageBox.information(
                self,
                "Импорт моделей",
                "Подходящих файлов не нашлось. Имена должны совпадать "
                "с названиями файлов из реестра моделей.",
            )
        self.reload()
