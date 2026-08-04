"""Мастер первого запуска: выбор пресета и доставка моделей.

Мастер намеренно тонкий. Все решения — что входит в пресет, что уже на диске,
что нужно скачать и что придётся ставить руками — принимает
:class:`~voiceflow.core.models.manager.ModelManager`. Здесь только показ
и кнопки, поэтому логику можно править и проверять тестами без Qt.
"""

from __future__ import annotations

import logging
from pathlib import Path
from time import monotonic

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QGroupBox,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from voiceflow.core.models.catalog import ModelSpec
from voiceflow.core.models.manager import DownloadPlan, ModelManager
from voiceflow.core.models.presets import PresetSpec, apply_preset, list_presets
from voiceflow.core.settings.store import SettingsStore
from voiceflow.ui.formatting import human_duration as _human_duration
from voiceflow.ui.formatting import human_size as _human_size

logger = logging.getLogger(__name__)


#: Через столько без прироста байт загрузка считается остановившейся.
STALL_SECONDS = 90.0

#: Как часто опрашивается размер скачанного.
POLL_MS = 500


class _DownloadWorker(QThread):
    """Загрузка в отдельном потоке: окно не должно замирать на гигабайтах."""

    model_started = Signal(str, int, int)
    succeeded = Signal()
    failed = Signal(str)

    def __init__(self, manager: ModelManager, preset: str) -> None:
        super().__init__()
        self._manager = manager
        self._preset = preset

    def run(self) -> None:
        try:
            self._manager.download_missing(
                self._preset,
                on_model=lambda spec, index, count: self.model_started.emit(
                    spec.id, index, count
                ),
            )
        except Exception as exc:
            logger.exception("Загрузка моделей прервана")
            self.failed.emit(str(exc))
            return
        self.succeeded.emit()


class PresetPage(QWizardPage):
    """Выбор пресета качества."""

    def __init__(self, manager: ModelManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._manager = manager
        self.setTitle("Пресет качества")
        self.setSubTitle(
            "Пресет определяет, какие модели нужны и насколько быстро "
            "будет готов текст. Его можно сменить позже в настройках."
        )

        layout = QVBoxLayout(self)
        self._buttons: dict[str, QRadioButton] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        for spec in list_presets():
            layout.addWidget(self._build_option(spec))

        layout.addStretch(1)

    def _build_option(self, spec: PresetSpec) -> QGroupBox:
        box = QGroupBox()
        # Карточка без заголовка: имя отключает отступ, зарезервированный
        # под заголовок, иначе последняя строка описания обрезается.
        box.setObjectName("card")
        box_layout = QVBoxLayout(box)

        button = QRadioButton(spec.title)
        button.setChecked(spec.id == "standard")
        # Переключатели лежат в разных карточках, а Qt связывает их по общему
        # родителю. Без явной группы выбранными оказались бы сразу несколько.
        self._group.addButton(button)
        self._buttons[spec.id] = button
        box_layout.addWidget(button)

        plan = self._manager.download_plan(spec.id)
        details = QLabel(
            f"{spec.summary}\n"
            f"Требования: {spec.requirements}\n"
            f"Скорость: {spec.latency}\n"
            f"Загрузить: {_human_size(plan.total_bytes)}"
        )
        details.setWordWrap(True)
        details.setIndent(20)
        details.setProperty("role", "hint")
        # Без этого многострочная подпись обрезается: Qt отдаёт ей высоту
        # одной строки, пока перенос не посчитан.
        details.setSizePolicy(
            details.sizePolicy().horizontalPolicy(), QSizePolicy.Policy.MinimumExpanding
        )
        box_layout.addWidget(details)
        return box

    def selected_preset(self) -> str:
        for preset_id, button in self._buttons.items():
            if button.isChecked():
                return preset_id
        return "standard"


class DownloadPage(QWizardPage):
    """Список моделей пресета и их доставка."""

    def __init__(
        self,
        manager: ModelManager,
        preset_provider,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._manager = manager
        self._preset_provider = preset_provider
        self._worker: _DownloadWorker | None = None

        # Библиотека Hugging Face не сообщает прогресс наружу, поэтому объём
        # скачанного измеряется по файлам на диске.
        self._watch: ModelSpec | None = None
        self._watch_index = 0
        self._watch_count = 0
        self._watch_started = 0.0
        self._watch_from = 0
        self._last_growth = 0.0
        self._last_bytes = 0
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._poll_progress)

        self.setTitle("Модели")
        self.setSubTitle(
            "Модели не входят в установщик и хранятся отдельно от программы. "
            "Их можно скачать сейчас или подложить из готовой папки."
        )

        layout = QVBoxLayout(self)

        self._summary = QLabel()
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)

        self._listing = QTextEdit()
        self._listing.setReadOnly(True)
        layout.addWidget(self._listing, stretch=1)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        self._status = QLabel()
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._download_button = QPushButton("Загрузить недостающее")
        self._download_button.clicked.connect(self._start_download)
        layout.addWidget(self._download_button)

        self._folder_button = QPushButton("Взять из готовой папки…")
        self._folder_button.clicked.connect(self._import_from_folder)
        layout.addWidget(self._folder_button)

    def initializePage(self) -> None:  # noqa: N802 — имя задано Qt
        self._refresh()

    def _preset(self) -> str:
        return str(self._preset_provider())

    def _refresh(self) -> None:
        plan = self._manager.download_plan(self._preset())
        self._listing.setPlainText(self._describe(plan))

        if plan.is_complete:
            self._summary.setText("Всё необходимое уже на диске.")
            self._download_button.setEnabled(False)
        else:
            self._summary.setText(
                f"К загрузке {len(plan.missing)} шт., примерно "
                f"{_human_size(plan.total_bytes)}. Прерванная загрузка "
                "продолжится с того же места."
            )
            self._download_button.setEnabled(True)

        notes: list[str] = []
        if plan.manual:
            names = ", ".join(spec.title for spec in plan.manual)
            notes.append(f"Ставится вручную: {names}.")
        if plan.unavailable:
            names = ", ".join(spec.title for spec in plan.unavailable)
            notes.append(f"Пропущено, не установлен нужный пакет: {names}.")
        self._status.setText(" ".join(notes))

        self.completeChanged.emit()

    @staticmethod
    def _describe(plan: DownloadPlan) -> str:
        lines: list[str] = []
        for spec in plan.installed:
            lines.append(f"[есть]     {spec.title}")
        for spec in plan.missing:
            lines.append(f"[скачать]  {spec.title} — {_human_size(spec.size_bytes)}")
        for spec in plan.unavailable:
            lines.append(f"[нет пакета] {spec.title} — {spec.notes}")
        for spec in plan.manual:
            note = f" ({spec.notes})" if spec.notes else ""
            lines.append(f"[вручную]  {spec.title}{note}")
        return "\n".join(lines) or "Для этого пресета моделей не требуется."

    def isComplete(self) -> bool:  # noqa: N802 — имя задано Qt
        # Мастер не запирает пользователя: без моделей приложение запустится
        # и честно сообщит, чего не хватает.
        return self._worker is None

    # ------------------------------------------------------------------ #
    # Действия
    # ------------------------------------------------------------------ #

    def _set_busy(self, busy: bool) -> None:
        self._download_button.setEnabled(not busy)
        self._folder_button.setEnabled(not busy)
        self._progress.setVisible(busy)
        self.completeChanged.emit()

    def _start_download(self) -> None:
        if self._worker is not None:
            return
        worker = _DownloadWorker(self._manager, self._preset())
        worker.model_started.connect(self._on_model_started)
        worker.succeeded.connect(self._on_success)
        worker.failed.connect(self._on_failure)
        worker.finished.connect(self._on_worker_finished)
        self._worker = worker
        self._set_busy(True)
        self._status.setText("Готовлюсь к загрузке…")
        worker.start()

    def _on_model_started(self, model_id: str, index: int, count: int) -> None:
        spec = self._manager.catalog.by_id(model_id)
        self._watch = spec
        self._watch_index = index
        self._watch_count = count
        now = monotonic()
        self._watch_started = now
        self._last_growth = now
        self._watch_from = self._manager.downloaded_bytes(spec) if spec else 0
        self._last_bytes = self._watch_from
        self._progress.setValue(0)
        self._timer.start()

    def _poll_progress(self) -> None:
        """Показывает объём, скорость и остаток по файлам на диске."""
        spec = self._watch
        if spec is None:
            return

        done = self._manager.downloaded_bytes(spec)
        now = monotonic()
        if done > self._last_bytes:
            self._last_bytes = done
            self._last_growth = now

        total = spec.size_bytes
        self._progress.setValue(min(100, int(done * 100 / total)) if total else 0)

        prefix = f"Модель {self._watch_index} из {self._watch_count}"
        line = f"{prefix}: {spec.title} — {_human_size(done)} из {_human_size(total)}"

        elapsed = now - self._watch_started
        speed = (done - self._watch_from) / elapsed if elapsed > 1.0 else 0.0
        if speed > 1024:
            line = f"{line}, {_human_size(int(speed))}/с"
            remaining = total - done
            if remaining > 0:
                line = f"{line}, осталось {_human_duration(int(remaining / speed * 1000))}"

        idle = now - self._last_growth
        if idle > STALL_SECONDS:
            line = (
                f"{line}\nЗагрузка не двигается уже {_human_duration(int(idle * 1000))}. "
                "Проверьте соединение: нажмите «Отмена» и запустите загрузку заново, "
                "она продолжится с этого места."
            )
        self._status.setText(line)

    def _on_success(self) -> None:
        self._stop_watching()
        self._status.setText("Загрузка завершена.")

    def _on_failure(self, message: str) -> None:
        self._stop_watching()
        self._status.setText(f"Загрузка прервана: {message}")
        QMessageBox.warning(self, "Загрузка моделей", message)

    def _stop_watching(self) -> None:
        self._timer.stop()
        self._watch = None

    def _on_worker_finished(self) -> None:
        self._worker = None
        self._stop_watching()
        self._set_busy(False)
        self._refresh()

    def _import_from_folder(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Папка с готовыми моделями")
        if not directory:
            return
        try:
            imported = self._manager.import_from_folder(self._preset(), Path(directory))
        except OSError as exc:
            QMessageBox.warning(self, "Импорт моделей", str(exc))
            return

        if imported:
            self._status.setText(f"Взято из папки: {', '.join(imported)}")
        else:
            self._status.setText(
                "В папке не нашлось подходящих файлов. Имена должны совпадать "
                "с названиями из списка выше."
            )
        self._refresh()


class FirstRunWizard(QWizard):
    """Доводит чистую машину до рабочего состояния."""

    #: Пресет выбран и записан в настройки.
    preset_applied = Signal(str)

    def __init__(
        self,
        store: SettingsStore,
        manager: ModelManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._manager = manager or ModelManager()

        self.setWindowTitle("VoiceFlow — первый запуск")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.resize(620, 520)

        self._preset_page = PresetPage(self._manager)
        self._download_page = DownloadPage(self._manager, self._preset_page.selected_preset)
        self.addPage(self._preset_page)
        self.addPage(self._download_page)

        self.setButtonText(QWizard.WizardButton.FinishButton, "Готово")
        self.setButtonText(QWizard.WizardButton.NextButton, "Далее")
        self.setButtonText(QWizard.WizardButton.BackButton, "Назад")
        self.setButtonText(QWizard.WizardButton.CancelButton, "Отмена")

    def accept(self) -> None:
        preset_id = self._preset_page.selected_preset()
        settings = self._store.settings
        changes = apply_preset(settings, preset_id)
        for note in self._store.save(settings):
            logger.warning("Настройки: %s", note)
        if changes:
            logger.info("Пресет «%s»: %s", preset_id, "; ".join(changes))

        super().accept()
        self.preset_applied.emit(preset_id)
