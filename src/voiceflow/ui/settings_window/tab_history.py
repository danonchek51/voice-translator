"""Вкладка «История».

Показывает собственную историю VoiceFlow, а не системный буфер обмена.
Аудио не хранится: в записи только тексты и метрики.
"""

from __future__ import annotations

import logging
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from voiceflow.core.history import HistoryEntry, HistoryRepository, compute_stats
from voiceflow.core.settings.schema import HISTORY_LIMITS, Settings
from voiceflow.core.text.modes import get_step
from voiceflow.ui.formatting import human_duration
from voiceflow.ui.settings_window.common import SettingsTab

logger = logging.getLogger(__name__)


def _format_time(raw: str) -> str:
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError:
        return raw
    return moment.astimezone().strftime("%d.%m.%Y %H:%M:%S")


class HistoryTab(SettingsTab):
    sections = ("history",)

    copy_requested = Signal(str)
    paste_requested = Signal(str)

    def __init__(self, history: HistoryRepository) -> None:
        super().__init__()
        self._history = history

        layout = QVBoxLayout(self)

        options = QGroupBox("Хранение")
        options_form = QFormLayout(options)
        self.enabled = QCheckBox("Сохранять результаты обработки")
        self.enabled.setToolTip("Аудиозаписи не сохраняются никогда")
        self.max_entries = QComboBox()
        for limit in HISTORY_LIMITS:
            title = "Не сохранять" if limit == 0 else f"{limit} записей"
            self.max_entries.addItem(title, limit)
        options_form.addRow(self.enabled)
        options_form.addRow("Максимум записей", self.max_entries)
        layout.addWidget(options)

        self.stats = QLabel()
        self.stats.setWordWrap(True)
        layout.addWidget(self.stats)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Когда", "Режим", "Длительность"])
        self.tree.setRootIsDecorated(False)
        self.tree.currentItemChanged.connect(self._on_select)
        splitter.addWidget(self.tree)

        holder = QWidget()
        details = QVBoxLayout(holder)
        self.raw_text = self._add_view(details, "Сырой текст")
        self.clean_text = self._add_view(details, "Очищенный текст")
        self.final_text = self._add_view(details, "Итоговый текст")

        buttons = QHBoxLayout()
        copy_raw = QPushButton("Копировать сырой")
        copy_clean = QPushButton("Копировать очищенный")
        copy_final = QPushButton("Копировать итоговый")
        paste_final = QPushButton("Вставить итоговый")
        copy_raw.clicked.connect(lambda: self._copy(self.raw_text))
        copy_clean.clicked.connect(lambda: self._copy(self.clean_text))
        copy_final.clicked.connect(lambda: self._copy(self.final_text))
        paste_final.clicked.connect(self._paste_final)
        for button in (copy_raw, copy_clean, copy_final, paste_final):
            buttons.addWidget(button)
        details.addLayout(buttons)

        splitter.addWidget(holder)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, stretch=1)

        bottom = QHBoxLayout()
        self.delete_button = QPushButton("Удалить запись")
        self.clear_button = QPushButton("Очистить историю…")
        self.refresh_button = QPushButton("Обновить")
        self.delete_button.clicked.connect(self._delete)
        self.clear_button.clicked.connect(self._clear)
        self.refresh_button.clicked.connect(self.reload)
        bottom.addWidget(self.delete_button)
        bottom.addWidget(self.clear_button)
        bottom.addStretch(1)
        bottom.addWidget(self.refresh_button)
        layout.addLayout(bottom)

        self.add_reset_row(layout)

    @staticmethod
    def _add_view(layout: QVBoxLayout, title: str) -> QPlainTextEdit:
        layout.addWidget(QLabel(title))
        view = QPlainTextEdit()
        view.setReadOnly(True)
        layout.addWidget(view)
        return view

    # ------------------------------------------------------------------ #
    # Данные
    # ------------------------------------------------------------------ #

    def load_from(self, settings: Settings) -> None:
        self.enabled.setChecked(settings.history.enabled)
        index = self.max_entries.findData(settings.history.max_entries)
        self.max_entries.setCurrentIndex(max(0, index))
        self.reload()

    def apply_to(self, settings: Settings) -> None:
        settings.history.enabled = self.enabled.isChecked()
        settings.history.max_entries = int(self.max_entries.currentData())

    def reload(self) -> None:
        """Перечитывает записи. Показ идёт от новых к старым."""
        self.tree.clear()
        self._clear_views()

        entries = self._history.list_entries()
        for entry in entries:
            item = QTreeWidgetItem(
                [
                    _format_time(entry.created_at),
                    self._steps_title(entry.mode),
                    human_duration(entry.duration_ms),
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, entry)
            self.tree.addTopLevelItem(item)
        for column in range(3):
            self.tree.resizeColumnToContents(column)

        stats = compute_stats(self._history)
        if stats.fragments:
            self.stats.setText(
                f"Записей: {stats.fragments}. Речи: "
                f"{human_duration(stats.total_duration_ms)}. "
                f"Слов: {stats.total_words}, символов: {stats.total_chars}. "
                f"Средняя обработка: {stats.average_elapsed_ms:.0f} мс."
            )
        elif not self.enabled.isChecked() or self.max_entries.currentData() == 0:
            self.stats.setText("История выключена: база не создаётся, записи не ведутся.")
        else:
            self.stats.setText("Пока ничего не записано.")

        has_entries = bool(entries)
        self.delete_button.setEnabled(has_entries)
        self.clear_button.setEnabled(has_entries)

    @staticmethod
    def _steps_title(stored: str) -> str:
        """Читаемая цепочка шагов из того, что записано в историю."""
        if not stored:
            return "Без обработки"
        titles: list[str] = []
        for step_id in stored.split(","):
            step = get_step(step_id.strip())
            titles.append(step.title if step else step_id.strip())
        return " → ".join(titles)

    def _clear_views(self) -> None:
        for view in (self.raw_text, self.clean_text, self.final_text):
            view.clear()

    def _on_select(self, current: QTreeWidgetItem | None, _previous) -> None:
        if current is None:
            self._clear_views()
            return
        entry = current.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(entry, HistoryEntry):
            return
        self.raw_text.setPlainText(entry.raw_text)
        self.clean_text.setPlainText(entry.clean_text)
        self.final_text.setPlainText(entry.final_text)

    # ------------------------------------------------------------------ #
    # Действия
    # ------------------------------------------------------------------ #

    def _copy(self, view: QPlainTextEdit) -> None:
        text = view.toPlainText()
        if text:
            self.copy_requested.emit(text)

    def _paste_final(self) -> None:
        text = self.final_text.toPlainText()
        if text:
            self.paste_requested.emit(text)

    def _current_entry(self) -> HistoryEntry | None:
        item = self.tree.currentItem()
        if item is None:
            return None
        entry = item.data(0, Qt.ItemDataRole.UserRole)
        return entry if isinstance(entry, HistoryEntry) else None

    def _delete(self) -> None:
        entry = self._current_entry()
        if entry is None:
            return
        self._history.delete(entry.id)
        self.reload()

    def _clear(self) -> None:
        answer = QMessageBox.question(
            self, "Очистить историю", "Удалить все сохранённые результаты?"
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._history.clear()
        self.reload()
