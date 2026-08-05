"""Иконка в системном трее и её меню.

Трей — основной способ управления: окна у приложения обычно нет, а плашка
намеренно маленькая.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QMenu,
    QRadioButton,
    QSystemTrayIcon,
    QWidgetAction,
)

from voiceflow.core.models.presets import list_presets
from voiceflow.core.state import AppState
from voiceflow.core.text.modes import STEPS
from voiceflow.ui import icons, theme


def _widget_action(menu: QMenu, widget: QCheckBox | QRadioButton) -> QWidgetAction:
    """Пункт меню на виджете: клик не закрывает меню трея.

    Обычный :class:`QAction` после ``triggered`` прячет всё контекстное меню —
    переключить два шага подряд становится невозможно. У ``QWidgetAction``
    Qt оставляет меню открытым.
    """
    action = QWidgetAction(menu)
    action.setDefaultWidget(widget)
    menu.addAction(action)
    return action


class TrayIcon(QObject):
    """Обёртка над :class:`QSystemTrayIcon` с понятными сигналами."""

    start_recording_requested = Signal()
    stop_recording_requested = Signal()
    toggle_listening_requested = Signal()
    toggle_overlay_requested = Signal()
    history_requested = Signal()
    settings_requested = Signal()
    diagnostics_requested = Signal()
    quit_requested = Signal()
    #: Шаг обработки включён или выключен из меню: идентификатор и состояние.
    step_toggled = Signal(str, bool)
    #: Выбран пресет качества.
    preset_selected = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._state = AppState.IDLE

        self._icon = QSystemTrayIcon(icons.state_icon(AppState.IDLE), self)
        self._icon.setToolTip("VoiceFlow")

        self._menu = QMenu()

        self._start_action = QAction("Начать запись", self._menu)
        self._start_action.triggered.connect(lambda: self.start_recording_requested.emit())

        self._stop_action = QAction("Остановить запись", self._menu)
        self._stop_action.setEnabled(False)
        self._stop_action.triggered.connect(lambda: self.stop_recording_requested.emit())

        self._listening_action = QAction("Пауза прослушивания", self._menu)
        self._listening_action.setCheckable(True)
        self._listening_action.triggered.connect(
            lambda: self.toggle_listening_requested.emit()
        )

        self._overlay_action = QAction("Скрыть плашку", self._menu)
        self._overlay_action.triggered.connect(lambda: self.toggle_overlay_requested.emit())

        # Шаги обработки переключаются прямо здесь: это самое частое действие,
        # и ради него открывать окно настроек незачем.
        self._steps_menu = QMenu("Обработка", self._menu)
        self._step_checks: dict[str, QCheckBox] = {}
        # Совместимость с тестами: прежнее имя хранит те же виджеты.
        self._step_actions: dict[str, QCheckBox] = self._step_checks
        for step in STEPS:
            box = QCheckBox(step.title)
            box.setToolTip(step.description)
            box.toggled.connect(
                lambda checked, step_id=step.id: self.step_toggled.emit(step_id, checked)
            )
            _widget_action(self._steps_menu, box)
            self._step_checks[step.id] = box

        # Пресет меняет сразу и движок, и участие языковой модели.
        self._preset_menu = QMenu("Качество", self._menu)
        self._preset_radios: dict[str, QRadioButton] = {}
        self._preset_actions: dict[str, QRadioButton] = self._preset_radios
        for preset in list_presets():
            radio = QRadioButton(preset.title)
            radio.setToolTip(preset.summary)
            radio.toggled.connect(
                lambda checked, preset_id=preset.id: (
                    self.preset_selected.emit(preset_id) if checked else None
                )
            )
            _widget_action(self._preset_menu, radio)
            self._preset_radios[preset.id] = radio

        self._steps_action = QAction("Обработка: —", self._menu)
        self._steps_action.setEnabled(False)

        self._history_action = QAction("История", self._menu)
        self._history_action.triggered.connect(lambda: self.history_requested.emit())

        self._settings_action = QAction("Настройки", self._menu)
        self._settings_action.triggered.connect(lambda: self.settings_requested.emit())

        self._diagnostics_action = QAction("Диагностика", self._menu)
        self._diagnostics_action.triggered.connect(
            lambda: self.diagnostics_requested.emit()
        )

        self._quit_action = QAction("Выход", self._menu)
        self._quit_action.triggered.connect(lambda: self.quit_requested.emit())

        self._menu.addAction(self._start_action)
        self._menu.addAction(self._stop_action)
        self._menu.addSeparator()
        self._menu.addAction(self._listening_action)
        self._menu.addAction(self._overlay_action)
        self._menu.addSeparator()
        self._menu.addAction(self._steps_action)
        self._menu.addMenu(self._steps_menu)
        self._menu.addMenu(self._preset_menu)
        self._menu.addSeparator()
        self._menu.addAction(self._history_action)
        self._menu.addAction(self._settings_action)
        self._menu.addAction(self._diagnostics_action)
        self._menu.addSeparator()
        self._menu.addAction(self._quit_action)

        self._icon.setContextMenu(self._menu)

    @property
    def menu(self) -> QMenu:
        """Нужен плашке: правый щелчок по ней показывает то же меню."""
        return self._menu

    def show(self) -> None:
        self._icon.show()

    def hide(self) -> None:
        self._icon.hide()

    @staticmethod
    def is_available() -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def set_state(self, state: AppState, detail: str = "") -> None:
        self._state = state
        self._icon.setIcon(icons.state_icon(state))
        label = theme.style_for(state).label
        self._icon.setToolTip(f"VoiceFlow — {label}" + (f" ({detail})" if detail else ""))

        recording = state is AppState.RECORDING
        busy = state in (
            AppState.TRANSCRIBING,
            AppState.PROCESSING,
            AppState.PASTING,
        )
        self._start_action.setEnabled(not recording and not busy)
        self._stop_action.setEnabled(recording)

    def set_listening(self, listening: bool) -> None:
        """Отражает, открыт ли микрофон."""
        self._listening_action.setChecked(not listening)
        self._listening_action.setText(
            "Пауза прослушивания" if listening else "Возобновить прослушивание"
        )

    def set_overlay_visible(self, visible: bool) -> None:
        self._overlay_action.setText("Скрыть плашку" if visible else "Показать плашку")

    def set_steps(self, description: str) -> None:
        """Показывает, какие шаги обработки включены."""
        self._steps_action.setText(f"Обработка: {description}")

    def set_step_states(self, enabled: dict[str, bool]) -> None:
        """Отмечает включённые шаги в подменю."""
        for step_id, box in self._step_checks.items():
            wanted = bool(enabled.get(step_id))
            if box.isChecked() == wanted:
                continue
            box.blockSignals(True)
            box.setChecked(wanted)
            box.blockSignals(False)

    def set_preset(self, preset: str) -> None:
        """Отмечает выбранный пресет."""
        radio = self._preset_radios.get(preset)
        if radio is None or radio.isChecked():
            return
        radio.blockSignals(True)
        radio.setChecked(True)
        radio.blockSignals(False)

    def set_step_available(self, step_id: str, available: bool, reason: str = "") -> None:
        """Гасит шаг, который сейчас не сработает.

        Перевод и «Инструкция» без языковой модели молча ничего не делают —
        честнее показать это в меню, чем дать включить впустую.
        """
        box = self._step_checks.get(step_id)
        if box is None:
            return
        box.setEnabled(available)
        if not available and reason:
            box.setToolTip(reason)

    def notify(self, title: str, message: str, error: bool = False) -> None:
        """Всплывающее уведомление. Только для ошибок и долгих операций."""
        icon = (
            QSystemTrayIcon.MessageIcon.Critical
            if error
            else QSystemTrayIcon.MessageIcon.Information
        )
        self._icon.showMessage(title, message, icon, 5000)
