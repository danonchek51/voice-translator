"""Вкладка «Активация»."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
)

from voiceflow.core.settings.schema import Settings
from voiceflow.core.wake.matcher import phrase_risk
from voiceflow.ui.hints import ACTIVATION
from voiceflow.ui.settings_window.common import SettingsTab
from voiceflow.ui.widgets.shortcut_edit import MOUSE_TITLES, HotkeyEdit, MouseButtonEdit

#: Человеческие названия способов остановки записи.
STOP_MODE_TITLES = {
    "press_again": "Toggle — повторное нажатие останавливает",
    "hold": "Hold — запись идёт, пока клавиша удерживается",
    "phrase": "Отдельная голосовая команда остановки",
    "same_phrase": "Повторение той же голосовой команды",
}

#: Названия кнопок мыши живут рядом с виджетом захвата: там же они и
#: показываются, дублировать их здесь незачем.
MOUSE_BUTTON_TITLES = MOUSE_TITLES

RISK_TITLES = {
    "пусто": "введите фразу",
    "высокий": "высокий — короткое слово часто срабатывает случайно",
    "средний": "средний — надёжнее двухсловная фраза",
    "низкий": "низкий",
}


class ActivationTab(SettingsTab):
    sections = ("activation",)
    hints = ACTIVATION

    listening_toggle_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)

        # --- Голос ---------------------------------------------------- #
        voice = QGroupBox("Голосовая активация")
        voice_form = QFormLayout(voice)

        self.wake_enabled = QCheckBox("Слушать команду запуска")
        self.wake_enabled.setToolTip(
            "Микрофон остаётся открытым постоянно, системный индикатор будет гореть"
        )
        self.wake_phrase = QLineEdit()
        self.wake_phrase.textChanged.connect(self._update_risk)
        self.wake_risk = QLabel()
        self.stop_phrase = QLineEdit()

        self.sensitivity = QSlider(Qt.Orientation.Horizontal)
        self.sensitivity.setRange(1, 10)
        self.sensitivity.setTickInterval(1)
        self.sensitivity_value = QLabel()
        self.sensitivity.valueChanged.connect(
            lambda value: self.sensitivity_value.setText(
                f"{value} — {'строже' if value <= 3 else 'чутче' if value >= 8 else 'середина'}"
            )
        )

        self.cooldown_ms = QSpinBox()
        self.cooldown_ms.setRange(0, 10_000)
        self.cooldown_ms.setSingleStep(100)
        self.cooldown_ms.setSuffix(" мс")
        self.cooldown_ms.setToolTip("Задержка после срабатывания, гасит повторные ложные запуски")

        voice_form.addRow(self.wake_enabled)
        voice_form.addRow("Фраза запуска", self.wake_phrase)
        voice_form.addRow("Риск ложных срабатываний", self.wake_risk)
        voice_form.addRow("Фраза остановки", self.stop_phrase)
        voice_form.addRow("Чувствительность", self.sensitivity)
        voice_form.addRow("", self.sensitivity_value)
        voice_form.addRow("Задержка после срабатывания", self.cooldown_ms)
        layout.addWidget(voice)

        # --- Клавиатура и мышь ---------------------------------------- #
        manual = QGroupBox("Клавиатура и мышь")
        manual_form = QFormLayout(manual)
        self.hotkey = HotkeyEdit()
        self.mouse_button = MouseButtonEdit()
        self.stop_mode = QComboBox()
        for code, title in STOP_MODE_TITLES.items():
            self.stop_mode.addItem(title, code)
        manual_form.addRow("Горячая клавиша", self.hotkey)
        manual_form.addRow("Кнопка мыши", self.mouse_button)
        manual_form.addRow("Способ остановки", self.stop_mode)
        bind_hint = QLabel(
            "Щёлкните поле и нажмите нужную клавишу или кнопку мыши. "
            "Delete снимает назначение, Escape отменяет."
        )
        bind_hint.setWordWrap(True)
        bind_hint.setProperty("role", "hint")
        manual_form.addRow("", bind_hint)
        layout.addWidget(manual)

        # --- Границы записи -------------------------------------------- #
        limits = QGroupBox("Границы записи")
        limits_form = QFormLayout(limits)
        self.max_record_seconds = QSpinBox()
        self.max_record_seconds.setRange(10, 3600)
        self.max_record_seconds.setSuffix(" с")
        self.max_record_seconds.setToolTip("Защитный лимит действует всегда")
        self.silence_stop_enabled = QCheckBox("Останавливать запись после тишины")
        self.silence_stop_seconds = QDoubleSpinBox()
        self.silence_stop_seconds.setRange(1.0, 30.0)
        self.silence_stop_seconds.setSingleStep(0.5)
        self.silence_stop_seconds.setSuffix(" с")
        limits_form.addRow("Максимальная длительность", self.max_record_seconds)
        limits_form.addRow(self.silence_stop_enabled)
        limits_form.addRow("Секунд тишины", self.silence_stop_seconds)
        layout.addWidget(limits)

        # --- Прослушивание прямо сейчас -------------------------------- #
        runtime = QHBoxLayout()
        self.listening_state = QLabel()
        self.listening_button = QPushButton("Пауза прослушивания")
        self.listening_button.clicked.connect(self.listening_toggle_requested.emit)
        runtime.addWidget(self.listening_state)
        runtime.addStretch(1)
        runtime.addWidget(self.listening_button)
        layout.addLayout(runtime)

        layout.addStretch(1)
        self.add_reset_row(layout)

    def set_listening(self, listening: bool) -> None:
        """Отражает состояние микрофона прямо сейчас, а не значение настройки."""
        self.listening_state.setText(
            "Микрофон открыт" if listening else "Прослушивание на паузе"
        )
        self.listening_button.setText(
            "Пауза прослушивания" if listening else "Возобновить прослушивание"
        )

    def _update_risk(self, text: str) -> None:
        risk = phrase_risk(text)
        self.wake_risk.setText(RISK_TITLES.get(risk, risk))

    def load_from(self, settings: Settings) -> None:
        activation = settings.activation
        self.wake_enabled.setChecked(activation.wake_enabled)
        self.wake_phrase.setText(activation.wake_phrase)
        self.stop_phrase.setText(activation.stop_phrase)
        self.sensitivity.setValue(activation.sensitivity)
        self.sensitivity_value.setText(str(activation.sensitivity))
        self.cooldown_ms.setValue(activation.cooldown_ms)
        self.hotkey.set_value(activation.hotkey)
        self.mouse_button.set_value(activation.mouse_button)
        self._select(self.stop_mode, activation.stop_mode, "press_again")
        self.max_record_seconds.setValue(activation.max_record_seconds)
        self.silence_stop_enabled.setChecked(activation.silence_stop_enabled)
        self.silence_stop_seconds.setValue(activation.silence_stop_seconds)
        self._update_risk(activation.wake_phrase)

    def apply_to(self, settings: Settings) -> None:
        activation = settings.activation
        activation.wake_enabled = self.wake_enabled.isChecked()
        activation.wake_phrase = self.wake_phrase.text().strip()
        activation.stop_phrase = self.stop_phrase.text().strip()
        activation.sensitivity = self.sensitivity.value()
        activation.cooldown_ms = self.cooldown_ms.value()
        activation.hotkey = self.hotkey.value()
        activation.mouse_button = self.mouse_button.value()
        activation.stop_mode = str(self.stop_mode.currentData())
        activation.max_record_seconds = self.max_record_seconds.value()
        activation.silence_stop_enabled = self.silence_stop_enabled.isChecked()
        activation.silence_stop_seconds = float(self.silence_stop_seconds.value())

    @staticmethod
    def _select(combo: QComboBox, value: str, fallback: str) -> None:
        index = combo.findData(value)
        if index < 0:
            index = combo.findData(fallback)
        combo.setCurrentIndex(max(0, index))
