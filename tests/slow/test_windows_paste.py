"""Сквозная проверка платформенного слоя Windows.

Открывает Блокнот, доставляет туда текст средствами приложения и читает
содержимое обратно. Проверяет то, чего не покажут подставные реализации:
буфер обмена, возврат фокуса чужому окну и доставку скан-кодов.

Запускается вручную: ``uv run pytest -m slow``. Тест перехватывает клавиатуру
и открывает окно, поэтому в обычный прогон он не входит.
"""

from __future__ import annotations

import subprocess
import sys
import time

import pytest

from voiceflow.core.delivery import ResultDelivery
from voiceflow.core.settings.schema import OutputSettings

pytestmark = [pytest.mark.slow, pytest.mark.windows]

if sys.platform != "win32":
    pytest.skip("Проверка платформенного слоя Windows", allow_module_level=True)

#: Технические фрагменты в тексте намеренные: они проверяют, что путь и URL
#: доходят до целевого окна без искажений.
SAMPLE = "Проверка VoiceFlow: путь C:\\temp\\main.py и адрес https://example.com"


@pytest.fixture
def notepad():  # type: ignore[no-untyped-def]
    """Запускает Блокнот и отдаёт дескриптор его окна."""
    import win32gui
    import win32process

    process = subprocess.Popen(["notepad.exe"])
    found: list[int] = []

    def collect(candidate: int, _: object) -> None:
        if not win32gui.IsWindowVisible(candidate):
            return
        _, pid = win32process.GetWindowThreadProcessId(candidate)
        if pid == process.pid:
            found.append(candidate)

    handle = 0
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        found.clear()
        win32gui.EnumWindows(collect, None)
        if found:
            handle = found[0]
            break
        time.sleep(0.25)

    if not handle:
        process.kill()
        pytest.skip("Окно Блокнота не появилось")

    try:
        yield handle
    finally:
        process.kill()
        process.wait(timeout=5)


def test_clipboard_roundtrip() -> None:
    from voiceflow.platform.windows.clipboard import WindowsClipboard

    clipboard = WindowsClipboard()

    assert clipboard.set_text("проба пера") is True
    assert clipboard.get_text() == "проба пера"


def test_text_reaches_another_window_unchanged(notepad: int) -> None:
    from pynput import keyboard

    from voiceflow.platform.windows.clipboard import WindowsClipboard
    from voiceflow.platform.windows.foreground import WindowsForegroundWindows
    from voiceflow.platform.windows.paste import WindowsPaster

    clipboard = WindowsClipboard()
    windows = WindowsForegroundWindows()

    assert windows.exists(notepad)
    assert windows.activate(notepad), "Не удалось вернуть фокус окну Блокнота"
    time.sleep(0.3)
    assert windows.is_active(notepad)

    settings = OutputSettings()
    settings.paste_delay_ms = 200
    delivery = ResultDelivery(
        settings_provider=lambda: settings,
        clipboard=clipboard,
        windows=windows,
        paster=WindowsPaster(),
    )

    result = delivery.deliver(SAMPLE, delivery.capture_target())

    assert result.copied is True
    assert result.pasted is True, result.message
    time.sleep(0.5)

    # Читаем обратно: выделяем всё и копируем штатными средствами системы.
    controller = keyboard.Controller()
    with controller.pressed(keyboard.Key.ctrl):
        controller.tap("a")
    time.sleep(0.2)
    with controller.pressed(keyboard.Key.ctrl):
        controller.tap("c")
    time.sleep(0.4)

    assert SAMPLE in (clipboard.get_text() or ""), "Текст дошёл искажённым"


def test_send_input_does_not_break_other_libraries() -> None:
    """Общий ctypes.windll кэширует функции: свои argtypes нельзя ставить в нём.

    Иначе ``SendInput`` ломается у любой другой библиотеки в процессе.
    """
    from pynput import keyboard

    from voiceflow.platform.windows import paste  # noqa: F401 - важен сам импорт

    controller = keyboard.Controller()
    controller.press(keyboard.Key.shift)
    controller.release(keyboard.Key.shift)
