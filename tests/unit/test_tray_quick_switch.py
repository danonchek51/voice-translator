"""Быстрое переключение из меню трея.

Смена шага обработки — самое частое действие. Ради него не должно
открываться окно настроек.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from voiceflow.core.text.modes import STEPS


@pytest.fixture(scope="module")
def qt_app() -> Iterator[object]:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


@pytest.fixture
def tray(qt_app):  # type: ignore[no-untyped-def]
    from voiceflow.ui.tray import TrayIcon

    icon = TrayIcon()
    yield icon
    icon.hide()


def test_every_step_is_in_the_menu(tray) -> None:  # type: ignore[no-untyped-def]
    for step in STEPS:
        assert step.id in tray._step_actions, f"шага «{step.id}» нет в меню"


def test_every_preset_is_in_the_menu(tray) -> None:  # type: ignore[no-untyped-def]
    from voiceflow.core.models.presets import PRESET_SPECS

    for preset in PRESET_SPECS:
        assert preset in tray._preset_actions


def test_toggling_a_step_reports_it(tray) -> None:  # type: ignore[no-untyped-def]
    seen: list[tuple[str, bool]] = []
    tray.step_toggled.connect(lambda step_id, on: seen.append((step_id, on)))

    action = tray._step_actions["translate"]
    action.setChecked(True)
    action.trigger()

    assert seen and seen[-1][0] == "translate"


def test_menu_shows_current_state(tray) -> None:  # type: ignore[no-untyped-def]
    tray.set_step_states({"clean": True, "translate": False, "prompt": False})

    assert tray._step_actions["clean"].isChecked()
    assert not tray._step_actions["translate"].isChecked()


def test_preset_selection_reports_it(tray) -> None:  # type: ignore[no-untyped-def]
    chosen: list[str] = []
    tray.preset_selected.connect(chosen.append)

    tray._preset_actions["light"].trigger()

    assert chosen == ["light"]


def test_only_one_preset_stays_marked(tray) -> None:  # type: ignore[no-untyped-def]
    tray.set_preset("standard")
    tray.set_preset("quality")

    marked = [name for name, a in tray._preset_actions.items() if a.isChecked()]

    assert marked == ["quality"]


def test_unavailable_step_is_greyed_with_reason(tray) -> None:  # type: ignore[no-untyped-def]
    """Без языковой модели перевод молча ничего не делает — честнее погасить."""
    tray.set_step_available("translate", False, "Нужна языковая модель.")

    action = tray._step_actions["translate"]

    assert not action.isEnabled()
    assert "языковая модель" in action.toolTip()


def test_available_step_is_clickable(tray) -> None:  # type: ignore[no-untyped-def]
    tray.set_step_available("translate", True)

    assert tray._step_actions["translate"].isEnabled()


def test_steps_summary_is_shown(tray) -> None:  # type: ignore[no-untyped-def]
    tray.set_steps("Очистка → Перевод")

    assert "Очистка → Перевод" in tray._steps_action.text()


def test_steps_have_explanations(tray) -> None:  # type: ignore[no-untyped-def]
    for step_id, action in tray._step_actions.items():
        assert action.toolTip(), f"шаг «{step_id}» без объяснения"
