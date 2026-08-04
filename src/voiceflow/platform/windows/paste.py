"""Отправка нажатий через ``SendInput``.

Ключевое решение — скан-коды вместо виртуальных клавиш. Виртуальная клавиша
``V`` на русской раскладке отображается на другую физическую кнопку, и вставка
срабатывала бы не всегда. Скан-код описывает именно физическую клавишу,
поэтому сочетание работает одинаково на любой раскладке.

Инъектированные события помечаются подписью в ``dwExtraInfo``: так собственные
перехватчики отличают свой ввод от пользовательского и не запускают запись
сами от себя.

Чего этот способ принципиально не умеет:

* доставить ввод в окно, запущенное от администратора, если приложение
  работает без повышенных прав (механизм UIPI);
* повлиять на игры, читающие ввод через Raw Input или DirectInput;
* пробиться через защищённые поля ввода банковских клиентов и RDP.
"""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

logger = logging.getLogger(__name__)

INPUT_KEYBOARD = 1

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008

#: Скан-коды по набору 1. Не зависят от раскладки.
SCAN_LCTRL = 0x1D
SCAN_LSHIFT = 0x2A
SCAN_V = 0x2F
SCAN_INSERT = 0x52

#: Подпись собственного ввода, чтобы не реагировать на него своими же хуками.
VOICEFLOW_SIGNATURE = 0x56464C57

ULONG_PTR = (
    ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong
)


class _KeyboardInput(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _HardwareInput(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _InputUnion(ctypes.Union):
    _fields_ = [  # noqa: RUF012 - формат задан ctypes, ClassVar здесь неприменим
        ("ki", _KeyboardInput),
        ("mi", _MouseInput),
        ("hi", _HardwareInput),
    ]


class _Input(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("value", _InputUnion)]


# Собственный экземпляр библиотеки, а не общий ctypes.windll: тот кэширует
# указатели на функции, и заданные здесь argtypes сломали бы SendInput
# у любой другой библиотеки в процессе, например у pynput.
# use_last_error нужен, чтобы ctypes сохранял код ошибки Windows.
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_Input), ctypes.c_int]
_user32.SendInput.restype = wintypes.UINT

#: Максимальная длина текста для посимвольного ввода. Дальше это слишком
#: медленно и заметно мешает пользователю.
MAX_TYPED_CHARS = 5000


def _key_event(scan: int, *, up: bool, extended: bool = False) -> _Input:
    flags = KEYEVENTF_SCANCODE
    if up:
        flags |= KEYEVENTF_KEYUP
    if extended:
        flags |= KEYEVENTF_EXTENDEDKEY
    event = _Input()
    event.type = INPUT_KEYBOARD
    event.value.ki = _KeyboardInput(
        wVk=0,
        wScan=scan,
        dwFlags=flags,
        time=0,
        dwExtraInfo=VOICEFLOW_SIGNATURE,
    )
    return event


def _unicode_event(code_unit: int, *, up: bool) -> _Input:
    flags = KEYEVENTF_UNICODE
    if up:
        flags |= KEYEVENTF_KEYUP
    event = _Input()
    event.type = INPUT_KEYBOARD
    event.value.ki = _KeyboardInput(
        wVk=0,
        wScan=code_unit,
        dwFlags=flags,
        time=0,
        dwExtraInfo=VOICEFLOW_SIGNATURE,
    )
    return event


def _send(events: list[_Input]) -> bool:
    if not events:
        return True
    count = len(events)
    array = (_Input * count)(*events)
    ctypes.set_last_error(0)
    sent = _user32.SendInput(count, array, ctypes.sizeof(_Input))
    if sent != count:
        logger.warning(
            "SendInput доставил %s из %s событий (код %s). "
            "Обычно это значит, что целевое окно запущено от администратора.",
            sent,
            count,
            ctypes.get_last_error(),
        )
        return False
    return True


class WindowsPaster:
    """Реализация :class:`~voiceflow.platform.base.Paster`."""

    def paste(self, method: str) -> bool:
        if method == "shift_insert":
            return self._shift_insert()
        if method == "ctrl_v":
            return self._ctrl_v()
        logger.error("Неизвестный способ вставки: %s", method)
        return False

    @staticmethod
    def _ctrl_v() -> bool:
        return _send(
            [
                _key_event(SCAN_LCTRL, up=False),
                _key_event(SCAN_V, up=False),
                _key_event(SCAN_V, up=True),
                _key_event(SCAN_LCTRL, up=True),
            ]
        )

    @staticmethod
    def _shift_insert() -> bool:
        # Insert — расширенная клавиша, без флага система примет её за цифру 0.
        return _send(
            [
                _key_event(SCAN_LSHIFT, up=False),
                _key_event(SCAN_INSERT, up=False, extended=True),
                _key_event(SCAN_INSERT, up=True, extended=True),
                _key_event(SCAN_LSHIFT, up=True),
            ]
        )

    def type_text(self, text: str) -> bool:
        """Посимвольный ввод для окон, не читающих буфер обмена."""
        if not text:
            return True
        if len(text) > MAX_TYPED_CHARS:
            logger.error(
                "Текст длиной %s символов слишком велик для посимвольного ввода",
                len(text),
            )
            return False

        events: list[_Input] = []
        # Символы вне основной плоскости передаются суррогатной парой,
        # поэтому текст разбирается на кодовые единицы UTF-16.
        for unit in _utf16_units(text):
            events.append(_unicode_event(unit, up=False))
            events.append(_unicode_event(unit, up=True))
        return _send(events)


def _utf16_units(text: str) -> list[int]:
    data = text.encode("utf-16-le")
    return [
        int.from_bytes(data[index : index + 2], "little")
        for index in range(0, len(data), 2)
    ]
