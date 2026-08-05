"""Вкладка «Обработка».

Выбора режима здесь нет: обработка — цепочка шагов, каждый включается своей
галочкой. Порядок фиксирован, поэтому вкладка показывает итоговую цепочку
одной строкой — чтобы было видно, что произойдёт с текстом.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)

from voiceflow.core.settings.schema import Settings
from voiceflow.core.text.modes import STEPS, apply_step_enabled, describe
from voiceflow.ui.hints import PROCESSING
from voiceflow.ui.settings_window.common import SettingsTab

PASTE_METHOD_TITLES = {
    "ctrl_v": "Ctrl+V — подходит большинству окон",
    "shift_insert": "Shift+Insert — для терминалов",
    "unicode": "Посимвольный ввод — для окон, игнорирующих буфер",
}


class ProcessingTab(SettingsTab):
    sections = ("processing", "output")
    hints = PROCESSING

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)

        steps = QGroupBox("Что делать с распознанным текстом")
        steps_layout = QVBoxLayout(steps)
        steps_layout.addWidget(
            QLabel(
                "Шаги применяются по порядку. Перевод и «Инструкция для AI» "
                "взаимоисключающие: вместе они портят результат. "
                "Выключите все — получите дословный текст."
            )
        )

        self.step_boxes: dict[str, QCheckBox] = {}
        self._updating_exclusive = False
        for step in STEPS:
            box = QCheckBox(step.title)
            box.setToolTip(step.description)
            box.toggled.connect(
                lambda checked, step_id=step.id: self._on_step_toggled(step_id, checked)
            )
            steps_layout.addWidget(box)
            hint = QLabel(step.description)
            hint.setWordWrap(True)
            hint.setProperty("role", "hint")
            steps_layout.addWidget(hint)
            self.step_boxes[step.id] = box

        self.chain = QLabel()
        self.chain.setWordWrap(True)
        self.chain.setProperty("role", "accent")
        steps_layout.addWidget(self.chain)
        layout.addWidget(steps)

        text = QGroupBox("Текст")
        text_form = QFormLayout(text)
        self.glossary_enabled = QCheckBox("Применять пользовательский словарь замен")
        self.use_llm = QCheckBox("Использовать локальную языковую модель")
        self.use_llm.setToolTip(
            "Без модели остаётся только очистка по правилам: перевод "
            "и инструкция работать не будут"
        )
        self.guard_strict = QCheckBox("Строгая проверка ответа модели с откатом")
        self.guard_strict.setToolTip(
            "Откат — штатная деградация: смысл важнее красивой формулировки"
        )
        text_form.addRow(self.glossary_enabled)
        text_form.addRow(self.use_llm)
        text_form.addRow(self.guard_strict)
        layout.addWidget(text)

        output = QGroupBox("Вывод результата")
        output_form = QFormLayout(output)
        self.auto_paste = QCheckBox("Вставлять результат в активное окно")
        self.paste_delay_ms = QSpinBox()
        self.paste_delay_ms.setRange(0, 5000)
        self.paste_delay_ms.setSingleStep(50)
        self.paste_delay_ms.setSuffix(" мс")
        self.paste_delay_ms.setToolTip("Пауза на возврат фокуса перед нажатием вставки")
        self.paste_method = QComboBox()
        for code, title in PASTE_METHOD_TITLES.items():
            self.paste_method.addItem(title, code)
        self.confirm_if_window_changed = QCheckBox(
            "Не вставлять, если стало активным другое окно"
        )
        self.restore_clipboard = QCheckBox("Возвращать прежнее содержимое буфера обмена")
        self.restore_clipboard.setToolTip(
            "Через несколько секунд после вставки в буфер вернётся то, что было "
            "в нём раньше. Если вы за это время скопировали что-то своё, "
            "возврат не выполняется."
        )
        output_form.addRow(self.auto_paste)
        output_form.addRow("Задержка перед вставкой", self.paste_delay_ms)
        output_form.addRow("Способ вставки", self.paste_method)
        output_form.addRow(self.confirm_if_window_changed)
        output_form.addRow(self.restore_clipboard)
        layout.addWidget(output)

        layout.addStretch(1)
        self.add_reset_row(layout)

    def _on_step_toggled(self, step_id: str, checked: bool) -> None:
        """Перевод и «Инструкция» не уживаются — вторую галочку снимаем сами."""
        if self._updating_exclusive:
            self._update_chain()
            return
        if checked and step_id in ("translate", "prompt"):
            other = "prompt" if step_id == "translate" else "translate"
            box = self.step_boxes.get(other)
            if box is not None and box.isChecked():
                self._updating_exclusive = True
                box.setChecked(False)
                self._updating_exclusive = False
        self._update_chain()

    def _update_chain(self) -> None:
        """Показывает итоговую цепочку по текущим галочкам."""
        chosen = [step.title for step in STEPS if self.step_boxes[step.id].isChecked()]
        self.chain.setText(
            "Итог: " + (" → ".join(chosen) if chosen else "дословный текст без обработки")
        )

    def hint_targets(self) -> dict[str, QCheckBox]:
        """Шаги обработки живут в словаре, а не в отдельных полях.

        Ключом берётся имя настройки, а не идентификатор шага: у режима
        «Инструкция» они различаются, и подсказка прошла бы мимо.
        """
        return {
            step.enabled_by: self.step_boxes[step.id]
            for step in STEPS
            if step.id in self.step_boxes
        }

    def load_from(self, settings: Settings) -> None:
        processing = settings.processing
        # Старые профили могли включить перевод и инструкцию вместе — в истории
        # Downloads это давало ответ с заводским шаблоном вместо текста.
        if processing.translate_enabled and processing.prompt_mode_enabled:
            processing.translate_enabled = False
        for step in STEPS:
            box = self.step_boxes[step.id]
            box.blockSignals(True)
            box.setChecked(bool(getattr(processing, step.enabled_by, False)))
            box.blockSignals(False)
        self._update_chain()
        self.glossary_enabled.setChecked(processing.glossary_enabled)
        self.use_llm.setChecked(processing.use_llm)
        self.guard_strict.setChecked(processing.guard_strict)

        output = settings.output
        self.auto_paste.setChecked(output.auto_paste)
        self.paste_delay_ms.setValue(output.paste_delay_ms)
        index = self.paste_method.findData(output.paste_method)
        self.paste_method.setCurrentIndex(max(0, index))
        self.confirm_if_window_changed.setChecked(output.confirm_if_window_changed)
        self.restore_clipboard.setChecked(output.restore_clipboard)

    def apply_to(self, settings: Settings) -> None:
        processing = settings.processing
        for step in STEPS:
            apply_step_enabled(
                processing, step.id, self.step_boxes[step.id].isChecked()
            )
        processing.glossary_enabled = self.glossary_enabled.isChecked()
        processing.use_llm = self.use_llm.isChecked()
        processing.guard_strict = self.guard_strict.isChecked()

        output = settings.output
        output.auto_paste = self.auto_paste.isChecked()
        output.paste_delay_ms = self.paste_delay_ms.value()
        output.paste_method = str(self.paste_method.currentData())
        output.confirm_if_window_changed = self.confirm_if_window_changed.isChecked()
        output.restore_clipboard = self.restore_clipboard.isChecked()

    def chain_description(self, settings: Settings) -> str:
        return describe(settings.processing)
