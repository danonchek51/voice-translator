"""Окно настроек.

Тесты дымовые: проверяют, что вкладки собираются, показывают текущие значения,
сохраняют изменения через существующий SettingsStore и сбрасывают разделы.
Автозапуск подменяется, чтобы тест не трогал реестр пользователя.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from voiceflow import paths
from voiceflow.core.history import HistoryRepository
from voiceflow.core.models import ModelManager
from voiceflow.core.settings.schema import HistorySettings
from voiceflow.core.settings.store import SettingsStore

pytestmark = pytest.mark.gui

EXPECTED_TABS = [
    "Общие",
    "Активация",
    "Распознавание",
    "Обработка",
    "Инструкции",
    "Модели",
    "Оформление",
    "История",
    "Диагностика",
]


class FakeAutostart:
    """Автозапуск в памяти."""

    def __init__(self) -> None:
        self.enabled = False

    @property
    def is_supported(self) -> bool:
        return True

    @property
    def description(self) -> str:
        return "подставной автозапуск"

    def is_enabled(self) -> bool:
        return self.enabled

    def set_enabled(self, enabled: bool) -> bool:
        self.enabled = enabled
        return True


@pytest.fixture(scope="module")
def qt_app() -> Iterator[object]:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SettingsStore:
    """Профиль во временной папке: так пути store и paths совпадают, как в бою."""
    monkeypatch.setenv(paths.HOME_ENV_VAR, str(tmp_path / "home"))
    paths.ensure_user_dirs()
    store = SettingsStore()
    store.load()
    return store


@pytest.fixture
def history(tmp_path: Path) -> HistoryRepository:
    return HistoryRepository(
        settings_provider=lambda: HistorySettings(enabled=True, max_entries=50),
        db_path=tmp_path / "history.db",
    )


@pytest.fixture
def models(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModelManager:
    from voiceflow.core.models import manager as manager_module

    monkeypatch.setattr(manager_module.paths, "models_dir", lambda: tmp_path / "models")
    return ModelManager()


@pytest.fixture
def window(qt_app, store, models, history):  # type: ignore[no-untyped-def]
    from voiceflow.ui.settings_window import SettingsWindow

    created = SettingsWindow(store, models, history, autostart=FakeAutostart())
    yield created
    created.close()


@pytest.fixture
def confirm_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Подтверждает диалоги: сброс раздела спрашивает согласия."""
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    )
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)


# --------------------------------------------------------------------------- #
# Состав окна
# --------------------------------------------------------------------------- #


def test_window_has_all_tabs(window) -> None:
    titles = [window.tabs.tabText(index) for index in range(window.tabs.count())]
    assert titles == EXPECTED_TABS


def test_tabs_declare_their_settings_sections(window) -> None:
    assert window.general.sections == ("system",)
    assert window.activation.sections == ("activation",)
    assert window.recognition.sections == ("recognition", "audio")
    assert window.processing.sections == ("processing", "output")
    assert window.history.sections == ("history",)


# --------------------------------------------------------------------------- #
# Чтение и запись настроек
# --------------------------------------------------------------------------- #


def test_tabs_show_current_values(window, store) -> None:
    activation = store.settings.activation
    assert window.activation.wake_phrase.text() == activation.wake_phrase
    assert window.activation.max_record_seconds.value() == activation.max_record_seconds
    assert window.processing.use_llm.isChecked() is store.settings.processing.use_llm


def test_save_writes_changes_to_store(window, store, confirm_yes) -> None:
    window.activation.wake_phrase.setText("пиши текст")
    window.activation.sensitivity.setValue(8)
    window.processing.auto_paste.setChecked(False)
    window.processing.paste_delay_ms.setValue(400)

    window.save()

    assert store.settings.activation.wake_phrase == "пиши текст"
    assert store.settings.activation.sensitivity == 8
    assert store.settings.output.auto_paste is False
    assert store.settings.output.paste_delay_ms == 400
    # Сохраняются только отличия от заводских значений.
    assert "пиши текст" in store.user_file.read_text(encoding="utf-8")


def test_invalid_value_is_repaired_on_save(window, store, confirm_yes) -> None:
    # Пустая фраза запрещена схемой: настройки чинят себя сами.
    window.activation.wake_phrase.setText("   ")

    window.save()

    assert store.settings.activation.wake_phrase.strip()
    assert window.activation.wake_phrase.text() == store.settings.activation.wake_phrase


def test_reset_section_restores_factory_values(window, store, confirm_yes) -> None:
    window.activation.wake_phrase.setText("другая фраза")
    window.save()
    assert store.settings.activation.wake_phrase == "другая фраза"

    window.activation.reset_requested.emit()

    assert store.settings.activation.wake_phrase != "другая фраза"
    assert window.activation.wake_phrase.text() == store.settings.activation.wake_phrase


def test_reset_all_clears_every_section(window, store, confirm_yes) -> None:
    window.activation.wake_phrase.setText("другая фраза")
    window.processing.auto_paste.setChecked(False)
    window.save()

    window.general.reset_all_requested.emit()

    assert store.settings.activation.wake_phrase != "другая фраза"
    assert store.settings.output.auto_paste is True


def test_autostart_goes_through_platform_layer(window, store, confirm_yes) -> None:
    autostart = window.general._autostart
    window.general.autostart.setChecked(True)

    window.save()

    assert autostart.is_enabled()
    assert store.settings.system.autostart is True


# --------------------------------------------------------------------------- #
# История
# --------------------------------------------------------------------------- #


def test_history_tab_lists_entries_newest_first(window, history) -> None:
    history.add(raw_text="первый", clean_text="первый", final_text="первый", mode="clean")
    history.add(raw_text="второй", clean_text="второй", final_text="второй", mode="raw")

    window.history.reload()

    assert window.history.tree.topLevelItemCount() == 2
    window.history.tree.setCurrentItem(window.history.tree.topLevelItem(0))
    assert window.history.final_text.toPlainText() == "второй"


def test_history_delete_and_clear(window, history, confirm_yes) -> None:
    history.add(raw_text="а", clean_text="а", final_text="а", mode="clean")
    history.add(raw_text="б", clean_text="б", final_text="б", mode="clean")
    window.history.reload()

    window.history.tree.setCurrentItem(window.history.tree.topLevelItem(0))
    window.history._delete()
    assert history.count() == 1

    window.history._clear()
    assert history.count() == 0


def test_history_limit_is_saved(window, store, confirm_yes) -> None:
    index = window.history.max_entries.findData(10)
    window.history.max_entries.setCurrentIndex(index)

    window.save()

    assert store.settings.history.max_entries == 10


# --------------------------------------------------------------------------- #
# Инструкции, модели, диагностика
# --------------------------------------------------------------------------- #


def test_prompts_tab_lists_factory_instructions(window) -> None:
    from PySide6.QtCore import Qt

    ids = [
        window.prompts.list.item(row).data(Qt.ItemDataRole.UserRole)
        for row in range(window.prompts.list.count())
    ]
    assert "clean.ru" in ids
    assert "translate.en" in ids
    assert "prompt_engineer" in ids
    assert window.prompts.editor.toPlainText()


def test_prompts_test_button_runs_without_microphone(window, store) -> None:
    from voiceflow.core.text.processor import TextProcessor

    window.prompts._processor_provider = lambda: TextProcessor(
        settings_provider=lambda: store.settings.processing,
        fillers_provider=lambda: ("ну", "вот", "значит"),
    )
    window.prompts._show("clean.ru")
    window.prompts._test()

    assert "Результат:" in window.prompts.result.toPlainText()


def test_models_tab_shows_preset_composition(window) -> None:
    window.models.reload()

    assert window.models.tree.topLevelItemCount() > 0
    assert "Пресет" in window.models.preset_label.text()


def test_diagnostics_tab_shows_paths(window) -> None:
    text = window.diagnostics.report.toPlainText()

    assert "settings_file" in text
    assert "models_dir" in text


# --------------------------------------------------------------------------- #
# Перенос настроек
# --------------------------------------------------------------------------- #


def test_export_button_creates_bundle(
    window, store, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, confirm_yes
) -> None:
    from PySide6.QtWidgets import QFileDialog

    from voiceflow.core.settings.transfer import inspect_bundle

    archive = tmp_path / "экспорт.zip"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(archive), "")
    )
    window.activation.wake_phrase.setText("пиши текст")

    window.general.export_requested.emit()

    assert archive.is_file()
    info = inspect_bundle(archive)
    assert info.is_supported
    assert info.has_settings
