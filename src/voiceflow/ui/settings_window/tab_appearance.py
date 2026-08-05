"""Вкладка «Оформление».

Цвет меняется сразу, без сохранения и перезапуска: подобрать оттенок
вслепую по названию невозможно, его нужно видеть. При закрытии окна без
сохранения прежнее оформление возвращается.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
)

from voiceflow.core.settings.schema import Settings
from voiceflow.ui import style
from voiceflow.ui.hints import APPEARANCE
from voiceflow.ui.settings_window.common import SettingsTab

THEME_TITLES = {"dark": "Тёмная", "light": "Светлая"}

INDICATOR_TITLES = {
    "wave": "Волна",
    "bars": "Столбики",
    "pulse": "Пульс",
}


class ColorButton(QPushButton):
    """Кнопка-образец: показывает цвет и открывает палитру."""

    changed = Signal(str)

    def __init__(self, default_label: str = "Как в теме") -> None:
        super().__init__()
        self._value = ""
        self._default_label = default_label
        self.clicked.connect(self._pick)
        self.setMinimumWidth(160)
        self._refresh()

    def value(self) -> str:
        return self._value

    def set_value(self, colour: str) -> None:
        self._value = colour or ""
        self._refresh()

    def _pick(self) -> None:
        start = QColor(self._value) if self._value else QColor(style.PALETTE.accent)
        chosen = QColorDialog.getColor(start, self, "Выберите цвет")
        if chosen.isValid():
            self._value = chosen.name()
            self._refresh()
            self.changed.emit(self._value)

    def clear(self) -> None:
        self._value = ""
        self._refresh()
        self.changed.emit("")

    def _refresh(self) -> None:
        if self._value:
            self.setText(self._value.upper())
            # Подпись на образце должна читаться на любом фоне.
            ink = "#101215" if QColor(self._value).lightness() > 140 else "#f5f7fa"
            self.setStyleSheet(
                f"background: {self._value}; color: {ink}; border: none;"
            )
        else:
            self.setText(self._default_label)
            self.setStyleSheet("")


class AppearanceTab(SettingsTab):
    sections = ("appearance", "overlay")
    hints = APPEARANCE

    #: Оформление изменилось: окно применяет его немедленно.
    preview_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)

        colours = QGroupBox("Цвета")
        colours_form = QFormLayout(colours)

        self.theme = QComboBox()
        for code, title in THEME_TITLES.items():
            self.theme.addItem(title, code)
        self.theme.currentIndexChanged.connect(self._changed)

        self.accent = ColorButton()
        self.overlay_color = ColorButton()
        self.wave_color = ColorButton("Как акцент")
        for button in (self.accent, self.overlay_color, self.wave_color):
            button.changed.connect(self._changed)

        colours_form.addRow("Тема", self.theme)
        colours_form.addRow("Акцент", self._with_presets(self.accent))
        colours_form.addRow("Фон плашки", self._with_reset(self.overlay_color))
        colours_form.addRow("Цвет волны", self._with_reset(self.wave_color))
        layout.addWidget(colours)

        overlay = QGroupBox("Плашка")
        overlay_form = QFormLayout(overlay)

        self.indicator = QComboBox()
        for code, title in INDICATOR_TITLES.items():
            self.indicator.addItem(title, code)
        self.indicator.currentIndexChanged.connect(self._changed)

        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(30, 100)
        self.opacity.valueChanged.connect(self._on_opacity)
        self.opacity_value = QLabel()

        self.scale = QSlider(Qt.Orientation.Horizontal)
        self.scale.setRange(80, 200)
        self.scale.setSingleStep(10)
        self.scale.valueChanged.connect(self._on_scale)
        self.scale_value = QLabel()

        self.always_on_top = QCheckBox("Поверх остальных окон")
        self.always_on_top.toggled.connect(self._changed)

        overlay_form.addRow("Индикатор микрофона", self.indicator)
        overlay_form.addRow("Прозрачность", self._with_value(self.opacity, self.opacity_value))
        overlay_form.addRow("Размер", self._with_value(self.scale, self.scale_value))
        overlay_form.addRow(self.always_on_top)
        layout.addWidget(overlay)

        note = QLabel(
            "Изменения видны сразу. Если закрыть окно без сохранения, "
            "вернётся прежнее оформление."
        )
        note.setWordWrap(True)
        note.setProperty("role", "hint")
        layout.addWidget(note)

        layout.addStretch(1)
        self.add_reset_row(layout)

    # ------------------------------------------------------------------ #
    # Сборка строк
    # ------------------------------------------------------------------ #

    def _with_presets(self, button: ColorButton):  # type: ignore[no-untyped-def]
        row = QHBoxLayout()
        row.addWidget(button)
        chooser = QComboBox()
        chooser.addItem("Готовые цвета", "")
        for title, colour in style.ACCENT_PRESETS.items():
            chooser.addItem(title, colour)
        chooser.currentIndexChanged.connect(
            lambda: self._apply_preset(button, chooser.currentData())
        )
        row.addWidget(chooser)
        row.addStretch(1)
        return _wrap(row)

    def _with_reset(self, button: ColorButton):  # type: ignore[no-untyped-def]
        row = QHBoxLayout()
        row.addWidget(button)
        reset = QPushButton("Сбросить")
        reset.clicked.connect(button.clear)
        row.addWidget(reset)
        row.addStretch(1)
        return _wrap(row)

    @staticmethod
    def _with_value(slider: QSlider, label: QLabel):  # type: ignore[no-untyped-def]
        row = QHBoxLayout()
        row.addWidget(slider)
        row.addWidget(label)
        return _wrap(row)

    def _apply_preset(self, button: ColorButton, colour: str) -> None:
        if colour:
            button.set_value(colour)
            self._changed()

    # ------------------------------------------------------------------ #
    # Значения
    # ------------------------------------------------------------------ #

    def _changed(self) -> None:
        self.preview_requested.emit()

    def _on_opacity(self, value: int) -> None:
        self.opacity_value.setText(f"{value} %")
        self._changed()

    def _on_scale(self, value: int) -> None:
        self.scale_value.setText(f"{value} %")
        self._changed()

    def load_from(self, settings: Settings) -> None:
        appearance = settings.appearance
        self._select(self.theme, appearance.theme)
        self.accent.set_value(appearance.accent)
        self.overlay_color.set_value(appearance.overlay_color)
        self.wave_color.set_value(appearance.wave_color)
        self._select(self.indicator, appearance.indicator)

        overlay = settings.overlay
        self.opacity.setValue(overlay.opacity)
        self.opacity_value.setText(f"{overlay.opacity} %")
        self.scale.setValue(overlay.scale)
        self.scale_value.setText(f"{overlay.scale} %")
        self.always_on_top.setChecked(overlay.always_on_top)

    def apply_to(self, settings: Settings) -> None:
        appearance = settings.appearance
        appearance.theme = str(self.theme.currentData())
        appearance.accent = self.accent.value()
        appearance.overlay_color = self.overlay_color.value()
        appearance.wave_color = self.wave_color.value()
        appearance.indicator = str(self.indicator.currentData())

        settings.overlay.opacity = self.opacity.value()
        settings.overlay.scale = self.scale.value()
        settings.overlay.always_on_top = self.always_on_top.isChecked()

    @staticmethod
    def _select(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(max(0, index))


def _wrap(row: QHBoxLayout):  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QWidget

    holder = QWidget()
    row.setContentsMargins(0, 0, 0, 0)
    holder.setLayout(row)
    return holder
