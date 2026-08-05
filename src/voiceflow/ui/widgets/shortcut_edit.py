"""Назначение горячей клавиши и кнопки мыши нажатием.

Раньше сочетание вводилось текстом в формате pynput. Это требовало знать
формат, легко приводило к опечатке и молчаливо оставляло приложение без
горячей клавиши. Здесь поле само слушает нажатие: щёлкнул, нажал — готово.

Виджеты знают о формате pynput, потому что именно он лежит в настройках и
именно его читает платформенный слой. Преобразование собрано в одном месте,
чтобы правка формата не разъехалась по интерфейсу.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QPushButton, QWidget

#: Модификаторы в порядке, принятом в записи сочетаний.
_MODIFIERS: tuple[tuple[Qt.KeyboardModifier, str], ...] = (
    (Qt.KeyboardModifier.ControlModifier, "<ctrl>"),
    (Qt.KeyboardModifier.AltModifier, "<alt>"),
    (Qt.KeyboardModifier.ShiftModifier, "<shift>"),
    (Qt.KeyboardModifier.MetaModifier, "<cmd>"),
)

#: Клавиши без печатного знака. Имена — как их понимает pynput.
_NAMED_KEYS: dict[int, str] = {
    Qt.Key.Key_Space.value: "<space>",
    Qt.Key.Key_Tab.value: "<tab>",
    Qt.Key.Key_Return.value: "<enter>",
    Qt.Key.Key_Enter.value: "<enter>",
    Qt.Key.Key_Insert.value: "<insert>",
    Qt.Key.Key_Delete.value: "<delete>",
    Qt.Key.Key_Home.value: "<home>",
    Qt.Key.Key_End.value: "<end>",
    Qt.Key.Key_PageUp.value: "<page_up>",
    Qt.Key.Key_PageDown.value: "<page_down>",
    Qt.Key.Key_Up.value: "<up>",
    Qt.Key.Key_Down.value: "<down>",
    Qt.Key.Key_Left.value: "<left>",
    Qt.Key.Key_Right.value: "<right>",
    Qt.Key.Key_Pause.value: "<pause>",
    Qt.Key.Key_ScrollLock.value: "<scroll_lock>",
    Qt.Key.Key_Print.value: "<print_screen>",
}

#: Клавиши, которые сами по себе сочетанием не являются.
_BARE_MODIFIER_KEYS = frozenset(
    {
        Qt.Key.Key_Control.value,
        Qt.Key.Key_Alt.value,
        Qt.Key.Key_Shift.value,
        Qt.Key.Key_Meta.value,
        Qt.Key.Key_AltGr.value,
        Qt.Key.Key_CapsLock.value,
        Qt.Key.Key_NumLock.value,
    }
)

#: Кнопки мыши в терминах настроек.
_MOUSE_BUTTONS: dict[Qt.MouseButton, str] = {
    Qt.MouseButton.MiddleButton: "middle",
    Qt.MouseButton.BackButton: "x1",
    Qt.MouseButton.ForwardButton: "x2",
}

MOUSE_TITLES: dict[str, str] = {
    "none": "Не использовать",
    "x1": "Боковая кнопка «назад»",
    "x2": "Боковая кнопка «вперёд»",
    "middle": "Средняя кнопка (колесо)",
}

CAPTURE_PROMPT = "Нажмите сочетание…"
MOUSE_PROMPT = "Нажмите кнопку мыши по этому полю…"
EMPTY_TITLE = "Не назначено"


def key_event_to_hotkey(event: QKeyEvent) -> str:
    """Переводит нажатие в запись вида ``<ctrl>+<alt>+d``.

    Пустая строка означает, что нажатие сочетанием не является: например,
    нажат один модификатор и приложение ждёт основную клавишу.
    """
    key = int(event.key())
    if key in _BARE_MODIFIER_KEYS:
        return ""

    parts = [name for flag, name in _MODIFIERS if event.modifiers() & flag]
    main = _key_name(key, event.text())
    if not main:
        return ""

    parts.append(main)
    return "+".join(parts)


def _key_name(key: int, text: str) -> str:
    named = _NAMED_KEYS.get(key)
    if named:
        return named
    if Qt.Key.Key_F1.value <= key <= Qt.Key.Key_F35.value:
        return f"<f{key - Qt.Key.Key_F1.value + 1}>"
    if Qt.Key.Key_A.value <= key <= Qt.Key.Key_Z.value:
        return chr(key).lower()
    if Qt.Key.Key_0.value <= key <= Qt.Key.Key_9.value:
        return chr(key)
    # Печатный знак с раскладки: символ важнее кода клавиши.
    stripped = text.strip()
    if len(stripped) == 1:
        return stripped.lower()
    return ""


def hotkey_title(combination: str) -> str:
    """Человеческая подпись сочетания для кнопки."""
    if not combination:
        return EMPTY_TITLE
    titles = {
        "<ctrl>": "Ctrl",
        "<alt>": "Alt",
        "<shift>": "Shift",
        "<cmd>": "Win",
    }
    parts = []
    for chunk in combination.split("+"):
        chunk = chunk.strip()
        if chunk in titles:
            parts.append(titles[chunk])
        elif chunk.startswith("<") and chunk.endswith(">"):
            parts.append(chunk[1:-1].replace("_", " ").upper())
        else:
            parts.append(chunk.upper())
    return " + ".join(parts)


class _CaptureButton(QPushButton):
    """Кнопка, которая на время превращается в приёмник нажатий."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._capturing = False
        self.setCheckable(True)
        self.clicked.connect(self._toggle_capture)

    @property
    def is_capturing(self) -> bool:
        return self._capturing

    def _toggle_capture(self) -> None:
        self._set_capturing(not self._capturing)

    def _set_capturing(self, active: bool) -> None:
        self._capturing = active
        self.setChecked(active)
        if active:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            # Пока идёт захват, Tab и стрелки тоже должны доставаться нам,
            # иначе фокус уедет на соседний виджет вместо назначения клавиши.
            self.grabKeyboard()
        else:
            self.releaseKeyboard()
        self._refresh()

    def _refresh(self) -> None:
        raise NotImplementedError

    def focusOutEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        if self._capturing:
            self._set_capturing(False)
        super().focusOutEvent(event)


class HotkeyEdit(_CaptureButton):
    """Поле горячей клавиши: щёлкнуть и нажать сочетание."""

    changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        self._value = ""
        super().__init__(parent)
        self.setToolTip(
            "Щёлкните и нажмите сочетание. Escape — отмена, Delete — снять назначение."
        )
        self._refresh()

    def value(self) -> str:
        return self._value

    def set_value(self, combination: str) -> None:
        self._value = combination.strip()
        self._refresh()

    def _refresh(self) -> None:
        self.setText(CAPTURE_PROMPT if self.is_capturing else hotkey_title(self._value))

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 — имя из Qt
        if not self.is_capturing:
            super().keyPressEvent(event)
            return

        key = int(event.key())
        if key == Qt.Key.Key_Escape.value:
            self._set_capturing(False)
            event.accept()
            return
        if key in (Qt.Key.Key_Delete.value, Qt.Key.Key_Backspace.value):
            self._commit("")
            event.accept()
            return

        combination = key_event_to_hotkey(event)
        if combination:
            self._commit(combination)
        event.accept()

    def _commit(self, combination: str) -> None:
        self._value = combination
        self._set_capturing(False)
        self.changed.emit(combination)


class MouseButtonEdit(_CaptureButton):
    """Поле кнопки мыши: щёлкнуть, затем нажать нужную кнопку по этому полю."""

    changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        self._value = "none"
        super().__init__(parent)
        self.setToolTip(
            "Щёлкните, затем нажмите по этому полю боковую или среднюю кнопку. "
            "Escape — отмена, Delete — снять назначение."
        )
        self._refresh()

    def value(self) -> str:
        return self._value

    def set_value(self, button: str) -> None:
        self._value = button if button in MOUSE_TITLES else "none"
        self._refresh()

    def _refresh(self) -> None:
        self.setText(MOUSE_PROMPT if self.is_capturing else MOUSE_TITLES[self._value])

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 — имя из Qt
        if not self.is_capturing:
            super().mousePressEvent(event)
            return

        # Левая кнопка не назначается: ею пользователь щёлкает по интерфейсу.
        button = _MOUSE_BUTTONS.get(event.button())
        if button is not None:
            self._commit(button)
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 — имя из Qt
        if not self.is_capturing:
            super().keyPressEvent(event)
            return
        key = int(event.key())
        if key == Qt.Key.Key_Escape.value:
            self._set_capturing(False)
        elif key in (Qt.Key.Key_Delete.value, Qt.Key.Key_Backspace.value):
            self._commit("none")
        event.accept()

    def _commit(self, button: str) -> None:
        self._value = button
        self._set_capturing(False)
        self.changed.emit(button)
