"""Назначение горячей клавиши нажатием.

Раньше сочетание вводилось текстом в формате pynput: опечатка молча
оставляла приложение без горячей клавиши. Проверяем, что нажатие
превращается ровно в тот формат, который читает платформенный слой.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from voiceflow.ui.widgets.shortcut_edit import (
    EMPTY_TITLE,
    HotkeyEdit,
    MouseButtonEdit,
    hotkey_title,
    key_event_to_hotkey,
)


@pytest.fixture(scope="module")
def qt_app() -> Iterator[object]:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


def _key(key, modifiers=None, text=""):  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent

    return QKeyEvent(
        QKeyEvent.Type.KeyPress,
        key,
        modifiers if modifiers is not None else Qt.KeyboardModifier.NoModifier,
        text,
    )


# --------------------------------------------------------------------------- #
# Преобразование нажатия
# --------------------------------------------------------------------------- #


def test_combination_matches_pynput_format(qt_app) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt

    event = _key(
        Qt.Key.Key_D,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier,
        "d",
    )

    assert key_event_to_hotkey(event) == "<ctrl>+<alt>+d"


def test_combination_is_parseable_by_the_listener(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Формат обязан приниматься тем, кто ставит перехват."""
    pynput = pytest.importorskip("pynput")
    from PySide6.QtCore import Qt

    event = _key(
        Qt.Key.Key_J,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
        "j",
    )
    combination = key_event_to_hotkey(event)

    assert pynput.keyboard.HotKey.parse(combination)


def test_function_key_needs_no_modifier(qt_app) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt

    assert key_event_to_hotkey(_key(Qt.Key.Key_F9)) == "<f9>"


def test_named_keys_are_translated(qt_app) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt

    assert key_event_to_hotkey(_key(Qt.Key.Key_Space, text=" ")) == "<space>"
    assert "<page_up>" in key_event_to_hotkey(
        _key(Qt.Key.Key_PageUp, Qt.KeyboardModifier.ControlModifier)
    )


def test_lone_modifier_is_not_a_combination(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Пока нажат только Ctrl, назначать нечего — ждём основную клавишу."""
    from PySide6.QtCore import Qt

    assert key_event_to_hotkey(_key(Qt.Key.Key_Control)) == ""
    assert key_event_to_hotkey(_key(Qt.Key.Key_Shift)) == ""


def test_digit_and_letter_are_lowercase(qt_app) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt

    assert key_event_to_hotkey(_key(Qt.Key.Key_7, Qt.KeyboardModifier.AltModifier)) == "<alt>+7"
    assert key_event_to_hotkey(_key(Qt.Key.Key_Q, Qt.KeyboardModifier.AltModifier)) == "<alt>+q"


# --------------------------------------------------------------------------- #
# Подписи
# --------------------------------------------------------------------------- #


def test_title_is_readable() -> None:
    assert hotkey_title("<ctrl>+<alt>+d") == "Ctrl + Alt + D"
    assert hotkey_title("<f9>") == "F9"
    assert hotkey_title("") == EMPTY_TITLE


# --------------------------------------------------------------------------- #
# Поведение поля
# --------------------------------------------------------------------------- #


def test_field_captures_press(qt_app) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt

    field = HotkeyEdit()
    seen: list[str] = []
    field.changed.connect(seen.append)

    field.click()
    assert field.is_capturing
    field.keyPressEvent(
        _key(Qt.Key.Key_M, Qt.KeyboardModifier.ControlModifier, "m")
    )

    assert field.value() == "<ctrl>+m"
    assert seen == ["<ctrl>+m"]
    assert not field.is_capturing, "после назначения захват должен закончиться"
    assert field.text() == "Ctrl + M"


def test_escape_keeps_previous_value(qt_app) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt

    field = HotkeyEdit()
    field.set_value("<ctrl>+<alt>+d")
    field.click()
    field.keyPressEvent(_key(Qt.Key.Key_Escape))

    assert field.value() == "<ctrl>+<alt>+d"
    assert not field.is_capturing


def test_delete_clears_binding(qt_app) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt

    field = HotkeyEdit()
    field.set_value("<ctrl>+<alt>+d")
    field.click()
    field.keyPressEvent(_key(Qt.Key.Key_Delete))

    assert field.value() == ""
    assert field.text() == EMPTY_TITLE


def test_field_ignores_keys_until_clicked(qt_app) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt

    field = HotkeyEdit()
    field.set_value("<f5>")
    field.keyPressEvent(_key(Qt.Key.Key_K, text="k"))

    assert field.value() == "<f5>"


# --------------------------------------------------------------------------- #
# Кнопка мыши
# --------------------------------------------------------------------------- #


def _click(button):  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    point = QPointF(1.0, 1.0)
    return QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        point,
        point,
        point,
        button,
        button,
        Qt.KeyboardModifier.NoModifier,
    )


def test_side_buttons_are_captured(qt_app) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt

    field = MouseButtonEdit()
    field.click()
    field.mousePressEvent(_click(Qt.MouseButton.ForwardButton))

    assert field.value() == "x2"
    assert not field.is_capturing


def test_middle_button_is_captured(qt_app) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt

    field = MouseButtonEdit()
    field.click()
    field.mousePressEvent(_click(Qt.MouseButton.MiddleButton))

    assert field.value() == "middle"


def test_captured_button_is_known_to_settings(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Захваченное значение обязано пройти проверку схемы настроек."""
    from PySide6.QtCore import Qt

    from voiceflow.core.settings.schema import MOUSE_BUTTONS

    for button in (
        Qt.MouseButton.ForwardButton,
        Qt.MouseButton.BackButton,
        Qt.MouseButton.MiddleButton,
    ):
        field = MouseButtonEdit()
        field.click()
        field.mousePressEvent(_click(button))
        assert field.value() in MOUSE_BUTTONS


def test_delete_removes_mouse_binding(qt_app) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt

    field = MouseButtonEdit()
    field.set_value("x2")
    field.click()
    field.keyPressEvent(_key(Qt.Key.Key_Delete))

    assert field.value() == "none"
