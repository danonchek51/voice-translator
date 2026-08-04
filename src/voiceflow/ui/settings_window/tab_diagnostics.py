"""Вкладка «Диагностика»."""

from __future__ import annotations

import logging
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QGroupBox,
    QHBoxLayout,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from voiceflow.app import environment_report
from voiceflow.core.diagnostics.selftest import (
    CheckResult,
    check_microphone,
    check_paste,
    check_processing,
    check_recognition,
)
from voiceflow.core.settings.schema import Settings
from voiceflow.ui.settings_window.common import SettingsTab

logger = logging.getLogger(__name__)

#: Сколько секунд даётся на переключение в нужное окно перед проверкой вставки.
PASTE_SWITCH_SECONDS = 3


def _responsive_sleep(seconds: float) -> None:
    """Пауза, не подвешивающая окно: короткая проверка не стоит отдельного потока."""
    app = QApplication.instance()
    if app is not None:
        app.processEvents()
    time.sleep(seconds)


class DiagnosticsTab(SettingsTab):
    sections = ()

    def __init__(
        self,
        context_provider=None,
        capture_provider=None,
        transcribers_provider=None,
        processor_provider=None,
        delivery_provider=None,
    ) -> None:
        super().__init__()
        self._context_provider = context_provider
        self._capture_provider = capture_provider
        self._transcribers_provider = transcribers_provider
        self._processor_provider = processor_provider
        self._delivery_provider = delivery_provider

        layout = QVBoxLayout(self)

        environment = QGroupBox("Окружение и пути")
        environment_layout = QVBoxLayout(environment)
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setMaximumHeight(200)
        environment_layout.addWidget(self.report)
        layout.addWidget(environment)

        buttons = QHBoxLayout()
        self.mic_button = QPushButton("Проверить микрофон")
        self.asr_button = QPushButton("Проверить распознавание")
        self.processing_button = QPushButton("Проверить обработку")
        self.paste_button = QPushButton("Проверить вставку")
        self.mic_button.clicked.connect(self._check_microphone)
        self.asr_button.clicked.connect(self._check_recognition)
        self.processing_button.clicked.connect(self._check_processing)
        self.paste_button.clicked.connect(self._check_paste)
        for button in (
            self.mic_button,
            self.asr_button,
            self.processing_button,
            self.paste_button,
        ):
            buttons.addWidget(button)
        layout.addLayout(buttons)

        results = QGroupBox("Результаты проверок")
        results_layout = QVBoxLayout(results)
        self.results = QPlainTextEdit()
        self.results.setReadOnly(True)
        self.results.setPlaceholderText("Нажмите любую кнопку проверки")
        results_layout.addWidget(self.results)
        layout.addWidget(results, stretch=1)

        self.reload()

    def load_from(self, settings: Settings) -> None:
        self.reload()

    def reload(self) -> None:
        context = self._context_provider() if self._context_provider else None
        lines = [f"{key}: {value}" for key, value in environment_report(context).items()]
        self.report.setPlainText("\n".join(lines))

    # ------------------------------------------------------------------ #
    # Проверки
    # ------------------------------------------------------------------ #

    def _show(self, result: CheckResult) -> None:
        self.results.appendPlainText(result.as_line())
        self.results.appendPlainText("")

    def _check_microphone(self) -> None:
        if self._capture_provider is None:
            return
        self.results.appendPlainText("Говорите — слушаю секунду…")
        self.mic_button.setEnabled(False)
        try:
            result = check_microphone(self._capture_provider(), sleep=_responsive_sleep)
        finally:
            self.mic_button.setEnabled(True)
        self._show(result)

    def _check_recognition(self) -> None:
        if self._transcribers_provider is None:
            return
        self._show(check_recognition(self._transcribers_provider()))

    def _check_processing(self) -> None:
        if self._processor_provider is None:
            return
        self._show(check_processing(self._processor_provider()))

    def _check_paste(self) -> None:
        if self._delivery_provider is None:
            return
        QMessageBox.information(
            self,
            "Проверка вставки",
            f"После закрытия этого окна есть {PASTE_SWITCH_SECONDS} секунды, "
            "чтобы переключиться в нужное окно. Туда будет вставлена "
            "тестовая строка.",
        )
        self.paste_button.setEnabled(False)
        QTimer.singleShot(PASTE_SWITCH_SECONDS * 1000, self._run_paste_check)

    def _run_paste_check(self) -> None:
        try:
            result = check_paste(self._delivery_provider())
        finally:
            self.paste_button.setEnabled(True)
        self._show(result)
