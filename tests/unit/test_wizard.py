"""Мастер первого запуска.

Тест дымовой: он проверяет, что мастер собирается, показывает план загрузки
из реестра и записывает выбранный пресет в настройки. Сама загрузка моделей
здесь не выполняется — она требует сети и гигабайтов.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from voiceflow.core.models.manager import ModelManager
from voiceflow.core.settings.store import SettingsStore

pytestmark = pytest.mark.gui


@pytest.fixture(scope="module")
def qt_app() -> Iterator[object]:
    """Qt без окон: тест должен проходить на машине без графической сессии."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def store(tmp_path: Path) -> SettingsStore:
    store = SettingsStore(user_file=tmp_path / "settings.toml")
    store.load()
    return store


@pytest.fixture
def manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModelManager:
    from voiceflow.core.models import manager as manager_module

    monkeypatch.setattr(manager_module.paths, "models_dir", lambda: tmp_path / "models")
    return ModelManager()


def test_wizard_has_preset_and_download_pages(qt_app, store, manager) -> None:
    from voiceflow.ui.wizard import FirstRunWizard

    wizard = FirstRunWizard(store, manager)
    try:
        assert len(wizard.pageIds()) == 2
        # Без restart() у мастера ещё нет текущей страницы: её назначает показ.
        wizard.restart()
        assert wizard.currentPage().title() == "Пресет качества"
        wizard.next()
        assert wizard.currentPage().title() == "Модели"
    finally:
        wizard.close()


def test_wizard_shows_download_plan(qt_app, store, manager) -> None:
    from voiceflow.ui.wizard import DownloadPage, FirstRunWizard

    wizard = FirstRunWizard(store, manager)
    try:
        wizard.restart()
        wizard.next()
        page = wizard.currentPage()
        assert isinstance(page, DownloadPage)
        # На чистой машине качать есть что, и объём попадает в подпись страницы.
        plan = manager.download_plan("standard")
        assert plan.missing
        assert not plan.is_complete
        assert "К загрузке" in page._summary.text()
    finally:
        wizard.close()


def test_only_one_preset_stays_selected(qt_app, store, manager) -> None:
    """Переключатели лежат в разных карточках: без явной группы Qt их не свяжет."""
    from voiceflow.ui.wizard import FirstRunWizard

    wizard = FirstRunWizard(store, manager)
    try:
        buttons = wizard._preset_page._buttons
        buttons["light"].setChecked(True)

        checked = [name for name, button in buttons.items() if button.isChecked()]

        assert checked == ["light"]
        assert wizard._preset_page.selected_preset() == "light"

        buttons["quality"].setChecked(True)
        assert wizard._preset_page.selected_preset() == "quality"
    finally:
        wizard.close()


def test_finish_writes_preset_to_settings(qt_app, store, manager) -> None:
    from voiceflow.ui.wizard import FirstRunWizard

    wizard = FirstRunWizard(store, manager)
    applied: list[str] = []
    wizard.preset_applied.connect(applied.append)
    try:
        # Явно выбираем лёгкий пресет вместо предложенного по умолчанию.
        wizard._preset_page._buttons["light"].setChecked(True)
        wizard.accept()
    finally:
        wizard.close()

    assert applied == ["light"]
    assert store.settings.recognition.preset == "light"
    assert store.settings.processing.use_llm is False
    assert store.user_file.is_file()
