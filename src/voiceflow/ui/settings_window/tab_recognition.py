"""Вкладка «Распознавание»."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from voiceflow.core.audio.devices import list_input_devices
from voiceflow.core.models import ModelManager, list_presets
from voiceflow.core.settings.schema import ASR_ENGINES, Settings
from voiceflow.ui.formatting import human_size
from voiceflow.ui.settings_window.common import SettingsTab

ENGINE_TITLES = {
    "auto": "Автоматически по языку речи",
    "gigaam": "GigaAM — только русский, точнее и быстрее",
    "whisper": "Whisper — смешанная речь и английские термины",
}

LANGUAGE_MODE_TITLES = {
    "fixed": "Фиксированный язык",
    "auto": "Определять автоматически",
}


class RecognitionTab(SettingsTab):
    # Микрофон хранится в разделе audio, поэтому сброс затрагивает оба раздела.
    sections = ("recognition", "audio")

    def __init__(
        self,
        models: ModelManager,
        transcribers_provider=None,
    ) -> None:
        super().__init__()
        self._models = models
        self._transcribers_provider = transcribers_provider

        layout = QVBoxLayout(self)

        source = QGroupBox("Источник звука")
        source_form = QFormLayout(source)
        self.device = QComboBox()
        self.refresh_devices()
        refresh = QPushButton("Обновить список")
        refresh.clicked.connect(self.refresh_devices)
        source_form.addRow("Микрофон", self.device)
        source_form.addRow("", refresh)
        layout.addWidget(source)

        engine_box = QGroupBox("Движок и язык")
        engine_form = QFormLayout(engine_box)
        self.engine = QComboBox()
        for code in ASR_ENGINES:
            self.engine.addItem(ENGINE_TITLES.get(code, code), code)
        self.language_mode = QComboBox()
        for code, title in LANGUAGE_MODE_TITLES.items():
            self.language_mode.addItem(title, code)
        self.primary_language = QComboBox()
        self.primary_language.setEditable(True)
        self.primary_language.addItems(["ru", "en"])
        self.preset = QComboBox()
        for spec in list_presets():
            self.preset.addItem(spec.title, spec.id)
        self.preset.currentIndexChanged.connect(self.refresh_models)
        engine_form.addRow("Движок распознавания", self.engine)
        engine_form.addRow("Язык", self.language_mode)
        engine_form.addRow("Основной язык", self.primary_language)
        engine_form.addRow("Пресет качества", self.preset)
        layout.addWidget(engine_box)

        models_box = QGroupBox("Состояние локальных моделей")
        models_layout = QVBoxLayout(models_box)
        self.models_state = QPlainTextEdit()
        self.models_state.setReadOnly(True)
        self.models_state.setMaximumHeight(140)
        self.models_hint = QLabel()
        self.models_hint.setWordWrap(True)
        models_layout.addWidget(self.models_state)
        models_layout.addWidget(self.models_hint)
        layout.addWidget(models_box)

        layout.addStretch(1)
        self.add_reset_row(layout)

    # ------------------------------------------------------------------ #
    # Обновление списков
    # ------------------------------------------------------------------ #

    def refresh_devices(self) -> None:
        """Перечитывает устройства: их можно подключить, не закрывая окно."""
        current = self.device.currentData()
        self.device.clear()
        self.device.addItem("Системное по умолчанию", None)
        for item in list_input_devices():
            self.device.addItem(item.label(), item.index)
        if current is not None:
            index = self.device.findData(current)
            if index >= 0:
                self.device.setCurrentIndex(index)

    def refresh_models(self) -> None:
        """Показывает, что из моделей выбранного пресета уже на диске."""
        preset = str(self.preset.currentData() or "standard")
        plan = self._models.download_plan(preset)

        lines: list[str] = []
        for spec in plan.installed:
            lines.append(f"[есть]       {spec.title}")
        for spec in plan.missing:
            lines.append(f"[нет]        {spec.title} — {human_size(spec.size_bytes)}")
        for spec in plan.unavailable:
            lines.append(f"[нет пакета] {spec.title}")
        for spec in plan.manual:
            lines.append(f"[вручную]    {spec.title}")
        self.models_state.setPlainText("\n".join(lines) or "Моделей для пресета не задано.")

        if plan.missing:
            self.models_hint.setText(
                f"Не хватает {len(plan.missing)} моделей, примерно "
                f"{human_size(plan.total_bytes)}. Откройте вкладку «Модели» "
                "и загрузите их — до этого распознавание не запустится."
            )
        else:
            self.models_hint.setText(self._engine_summary())

    def _engine_summary(self) -> str:
        if self._transcribers_provider is None:
            return "Все модели пресета на месте."
        try:
            infos = self._transcribers_provider().describe_all()
        except Exception:
            return "Все модели пресета на месте."
        parts = [f"{info.title} ({info.device})" for info in infos]
        return "Все модели пресета на месте. Движки: " + ", ".join(parts)

    # ------------------------------------------------------------------ #
    # Настройки
    # ------------------------------------------------------------------ #

    def load_from(self, settings: Settings) -> None:
        self.refresh_devices()
        index = self.device.findData(settings.audio.device_id)
        self.device.setCurrentIndex(index if index >= 0 else 0)

        recognition = settings.recognition
        self._select(self.engine, recognition.engine, "auto")
        self._select(self.language_mode, recognition.language_mode, "fixed")
        self.primary_language.setCurrentText(recognition.primary_language)
        self._select(self.preset, recognition.preset, "standard")
        self.refresh_models()

    def apply_to(self, settings: Settings) -> None:
        device_id = self.device.currentData()
        settings.audio.device_id = int(device_id) if device_id is not None else None
        # Имя запоминаем рядом с индексом: на другом компьютере номера сдвинутся.
        settings.audio.device_name = (
            "" if device_id is None else self.device.currentText().replace(" (по умолчанию)", "")
        )

        recognition = settings.recognition
        recognition.engine = str(self.engine.currentData())
        recognition.language_mode = str(self.language_mode.currentData())
        recognition.primary_language = self.primary_language.currentText().strip() or "ru"
        recognition.preset = str(self.preset.currentData())

    @staticmethod
    def _select(combo: QComboBox, value: str, fallback: str) -> None:
        index = combo.findData(value)
        if index < 0:
            index = combo.findData(fallback)
        combo.setCurrentIndex(max(0, index))
