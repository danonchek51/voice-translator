"""Вкладка «Обработка».

Обработка — цепочка шагов. Каждый включается галочкой, порядок меняется
кнопками «выше / ниже». Итоговая цепочка видна одной строкой.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from voiceflow.core.settings.schema import Settings
from voiceflow.core.text.modes import (
    STEPS,
    STEPS_BY_ID,
    describe,
    normalize_step_order,
)
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
                "Как это работает:\n"
                "• шаги включаются галочками и идут сверху вниз;\n"
                "• «Очистка» правилами работает всегда; очистка моделью — "
                "уточнение, если модель доступна;\n"
                "• «Перевод» и «Инструкция для AI» всегда выдают английский "
                "и требуют готовую языковую модель (вкладка «Модели»);\n"
                "• если модели нет или она ещё качается — эти шаги не "
                "сработают, и вы получите уведомление;\n"
                "• все галочки выключены — в буфер уходит дословный текст."
            )
        )
        # Длинная подсказка: без переноса окно раздувается по ширине.
        intro = steps_layout.itemAt(steps_layout.count() - 1).widget()
        if isinstance(intro, QLabel):
            intro.setWordWrap(True)
            intro.setProperty("role", "hint")

        self._order: list[str] = [step.id for step in STEPS]
        self.step_boxes: dict[str, QCheckBox] = {}
        self._step_rows: dict[str, QWidget] = {}
        self._steps_host = QVBoxLayout()
        steps_layout.addLayout(self._steps_host)

        for step in STEPS:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            box = QCheckBox(step.title)
            box.setToolTip(step.description)
            box.toggled.connect(self._update_chain)
            up = QPushButton("↑")
            up.setFixedWidth(28)
            up.setToolTip("Выше в цепочке")
            up.clicked.connect(lambda _=False, sid=step.id: self._move(sid, -1))
            down = QPushButton("↓")
            down.setFixedWidth(28)
            down.setToolTip("Ниже в цепочке")
            down.clicked.connect(lambda _=False, sid=step.id: self._move(sid, 1))
            row_layout.addWidget(box, stretch=1)
            row_layout.addWidget(up)
            row_layout.addWidget(down)
            self.step_boxes[step.id] = box
            self._step_rows[step.id] = row
            hint = QLabel(step.description)
            hint.setWordWrap(True)
            hint.setProperty("role", "hint")
            # hint живёт под чекбоксом внутри той же строки-колонки
            wrap = QWidget()
            wrap_layout = QVBoxLayout(wrap)
            wrap_layout.setContentsMargins(0, 4, 0, 4)
            wrap_layout.setSpacing(2)
            wrap_layout.addWidget(row)
            wrap_layout.addWidget(hint)
            self._step_rows[step.id] = wrap

        self.chain = QLabel()
        self.chain.setWordWrap(True)
        self.chain.setProperty("role", "accent")
        steps_layout.addWidget(self.chain)
        layout.addWidget(steps)
        self._rebuild_step_rows()

        text = QGroupBox("Текст")
        text_form = QFormLayout(text)
        self.glossary_enabled = QCheckBox("Применять пользовательский словарь замен")
        self.use_llm = QCheckBox("Использовать локальную языковую модель")
        self.use_llm.setToolTip(
            "Без модели остаётся только очистка по правилам: перевод "
            "и инструкция работать не будут"
        )
        text_form.addRow(self.glossary_enabled)
        text_form.addRow(self.use_llm)
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
        output_form.addRow(self.auto_paste)
        output_form.addRow("Задержка перед вставкой", self.paste_delay_ms)
        output_form.addRow("Способ вставки", self.paste_method)
        output_form.addRow(self.confirm_if_window_changed)
        layout.addWidget(output)

        layout.addStretch(1)
        self.add_reset_row(layout)

    def _move(self, step_id: str, delta: int) -> None:
        index = self._order.index(step_id)
        target = index + delta
        if target < 0 or target >= len(self._order):
            return
        self._order[index], self._order[target] = self._order[target], self._order[index]
        self._rebuild_step_rows()
        self._update_chain()

    def _rebuild_step_rows(self) -> None:
        while self._steps_host.count():
            item = self._steps_host.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        for step_id in self._order:
            self._steps_host.addWidget(self._step_rows[step_id])

    def _update_chain(self) -> None:
        """Показывает итоговую цепочку по текущим галочкам и порядку."""
        chosen = [
            STEPS_BY_ID[step_id].title
            for step_id in self._order
            if self.step_boxes[step_id].isChecked()
        ]
        self.chain.setText(
            "Итог: " + (" → ".join(chosen) if chosen else "дословный текст без обработки")
        )

    def hint_targets(self) -> dict[str, QCheckBox]:
        """Шаги обработки живут в словаре, а не в отдельных полях."""
        return {
            step.enabled_by: self.step_boxes[step.id]
            for step in STEPS
            if step.id in self.step_boxes
        }

    def load_from(self, settings: Settings) -> None:
        processing = settings.processing
        self._order = list(normalize_step_order(processing.step_order))
        self._rebuild_step_rows()
        for step in STEPS:
            box = self.step_boxes[step.id]
            box.blockSignals(True)
            box.setChecked(bool(getattr(processing, step.enabled_by, False)))
            box.blockSignals(False)
        self._update_chain()
        self.glossary_enabled.setChecked(processing.glossary_enabled)
        self.use_llm.setChecked(processing.use_llm)

        output = settings.output
        self.auto_paste.setChecked(output.auto_paste)
        self.paste_delay_ms.setValue(output.paste_delay_ms)
        index = self.paste_method.findData(output.paste_method)
        self.paste_method.setCurrentIndex(max(0, index))
        self.confirm_if_window_changed.setChecked(output.confirm_if_window_changed)

    def apply_to(self, settings: Settings) -> None:
        processing = settings.processing
        for step in STEPS:
            setattr(processing, step.enabled_by, self.step_boxes[step.id].isChecked())
        processing.step_order = tuple(self._order)
        processing.glossary_enabled = self.glossary_enabled.isChecked()
        processing.use_llm = self.use_llm.isChecked()

        output = settings.output
        output.auto_paste = self.auto_paste.isChecked()
        output.paste_delay_ms = self.paste_delay_ms.value()
        output.paste_method = str(self.paste_method.currentData())
        output.confirm_if_window_changed = self.confirm_if_window_changed.isChecked()

    def chain_description(self, settings: Settings) -> str:
        return describe(settings.processing)
