"""Вкладка «Инструкции».

Редактор работает поверх существующего хранилища промптов: заводские файлы
лежат в ``config/prompts`` и только читаются, пользовательские правки
сохраняются в профиле и перекрывают заводские по имени. Своего формата
хранения вкладка не заводит.
"""

from __future__ import annotations

import difflib
import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from voiceflow.core.diagnostics.selftest import SAMPLE_TEXT
from voiceflow.core.llm.prompts import SHARED_RULES_ID, PromptError, PromptLibrary
from voiceflow.core.settings.schema import Settings
from voiceflow.core.text.modes import step_for_prompt
from voiceflow.ui.settings_window.common import SettingsTab

logger = logging.getLogger(__name__)

#: Понятные названия для файлов, у которых нет собственного шага.
SPECIAL_TITLES = {SHARED_RULES_ID: "Общие правила"}


class _DiffDialog(QDialog):
    """Отличия текущей инструкции от заводской."""

    def __init__(self, prompt_id: str, diff: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Отличия от заводской — {prompt_id}")
        self.resize(720, 520)
        layout = QVBoxLayout(self)
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setFont(QFont("Consolas"))
        view.setPlainText(diff or "Отличий нет: инструкция совпадает с заводской.")
        layout.addWidget(view)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.accept)
        layout.addWidget(close)


class PromptsTab(SettingsTab):
    # Инструкции хранятся отдельными файлами, а не в settings.toml,
    # поэтому кнопки сброса раздела здесь нет — есть «Вернуть заводскую».
    sections = ()

    def __init__(
        self,
        library: PromptLibrary | None = None,
        processor_provider=None,
    ) -> None:
        super().__init__()
        self._library = library or PromptLibrary()
        self._processor_provider = processor_provider
        self._current: str | None = None

        root = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._on_select)
        splitter.addWidget(self.list)

        holder = QWidget()
        right = QVBoxLayout(holder)
        self.usage = QLabel()
        self.usage.setWordWrap(True)
        self.editor = QPlainTextEdit()
        self.editor.setFont(QFont("Consolas"))

        buttons = QHBoxLayout()
        self.save_button = QPushButton("Сохранить")
        self.reset_button = QPushButton("Вернуть заводскую")
        self.diff_button = QPushButton("Показать отличия")
        self.test_button = QPushButton("Проверить на примере")
        self.save_button.clicked.connect(self._save)
        self.reset_button.clicked.connect(self._reset)
        self.diff_button.clicked.connect(self._diff)
        self.test_button.clicked.connect(self._test)
        for button in (
            self.save_button,
            self.reset_button,
            self.diff_button,
            self.test_button,
        ):
            buttons.addWidget(button)

        self.result = QPlainTextEdit()
        self.result.setReadOnly(True)
        self.result.setMaximumHeight(120)
        self.result.setPlaceholderText(
            "Здесь появится результат проверки инструкции на тестовом тексте"
        )

        right.addWidget(self.usage)
        right.addWidget(self.editor, stretch=1)
        right.addLayout(buttons)
        right.addWidget(self.result)
        splitter.addWidget(holder)
        splitter.setStretchFactor(1, 3)

        root.addWidget(splitter)
        self.reload()

    # ------------------------------------------------------------------ #
    # Список
    # ------------------------------------------------------------------ #

    def reload(self) -> None:
        """Перечитывает список инструкций и отмечает изменённые пользователем."""
        selected = self._current
        self.list.blockSignals(True)
        self.list.clear()
        for info in self._library.available():
            title = SPECIAL_TITLES.get(info.id, info.title or info.id)
            mark = " • изменено" if info.is_user_override else ""
            item = QListWidgetItem(f"{title}{mark}")
            item.setData(Qt.ItemDataRole.UserRole, info.id)
            self.list.addItem(item)
        self.list.blockSignals(False)

        target = selected or (
            str(self.list.item(0).data(Qt.ItemDataRole.UserRole))
            if self.list.count()
            else None
        )
        if target is not None:
            self._show(target)

    def _on_select(self, current: QListWidgetItem | None, _previous) -> None:
        if current is None:
            return
        self._show(str(current.data(Qt.ItemDataRole.UserRole)))

    def _show(self, prompt_id: str) -> None:
        self._current = prompt_id
        for row in range(self.list.count()):
            item = self.list.item(row)
            if str(item.data(Qt.ItemDataRole.UserRole)) == prompt_id:
                self.list.setCurrentRow(row)
                break

        if prompt_id == SHARED_RULES_ID:
            self.usage.setText(
                "Общие правила подмешиваются во все режимы. Правится в одном "
                "месте, применяется везде."
            )
        else:
            step = step_for_prompt(prompt_id)
            self.usage.setText(
                f"Применяется на шаге: {step.title}" if step else "Шаг не назначен"
            )

        try:
            self.editor.setPlainText(self._library.current_text(prompt_id))
        except PromptError as exc:
            self.editor.setPlainText("")
            self.usage.setText(str(exc))

        self.reset_button.setEnabled(self._library.is_modified(prompt_id))
        self.test_button.setEnabled(step_for_prompt(prompt_id) is not None)
        self.result.clear()

    # ------------------------------------------------------------------ #
    # Действия
    # ------------------------------------------------------------------ #

    def _save(self) -> None:
        if self._current is None:
            return
        try:
            self._library.save(self._current, self.editor.toPlainText())
        except PromptError as exc:
            QMessageBox.warning(self, "Инструкции", str(exc))
            return
        self.result.setPlainText("Инструкция сохранена в профиле пользователя.")
        self.reload()

    def _reset(self) -> None:
        if self._current is None:
            return
        answer = QMessageBox.question(
            self,
            "Вернуть заводскую",
            f"Удалить пользовательскую версию «{self._current}» "
            "и вернуть заводскую инструкцию?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._library.reset(self._current)
        self.result.setPlainText("Возвращена заводская инструкция.")
        self.reload()

    def _diff(self) -> None:
        if self._current is None:
            return
        try:
            factory = self._library.factory_text(self._current).splitlines()
        except PromptError as exc:
            QMessageBox.warning(self, "Инструкции", str(exc))
            return
        current = self.editor.toPlainText().splitlines()
        diff = "\n".join(
            difflib.unified_diff(
                factory,
                current,
                fromfile="заводская",
                tofile="текущая",
                lineterm="",
            )
        )
        _DiffDialog(self._current, diff, self).exec()

    def _test(self) -> None:
        """Прогоняет заранее подготовленный текст через один шаг.

        Микрофон не нужен, и настройки не учитываются: проверяется именно эта
        инструкция, а не текущая цепочка обработки.
        """
        prompt_id = self._current or ""
        if step_for_prompt(prompt_id) is None or self._processor_provider is None:
            self.result.setPlainText("Для этой инструкции проверка недоступна.")
            return

        try:
            outcome = self._processor_provider().preview(SAMPLE_TEXT, prompt_id)
        except Exception as exc:
            self.result.setPlainText(f"Проверка не удалась: {exc}")
            return

        detail = outcome.text or "(пустой результат)"
        if outcome.fallback_reason:
            detail = f"{detail}\n\nБез языковой модели: {outcome.fallback_reason}"
        self.result.setPlainText(
            f"Исходный текст:\n{SAMPLE_TEXT}\n\nРезультат:\n{detail}"
        )

    def load_from(self, settings: Settings) -> None:
        self.reload()
