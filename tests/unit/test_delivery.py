"""Доставка текста: буфер обмена, возврат фокуса, вставка.

Каждый шаг может не сработать по своей причине, и от каждой причины
пользователь должен получить понятное сообщение, не потеряв текст.
"""

from __future__ import annotations

import pytest

from tests.fakes import FakeClipboard, FakePaster, FakeWindows
from voiceflow.core.delivery import ResultDelivery
from voiceflow.core.settings.schema import OutputSettings
from voiceflow.platform.base import WindowInfo


class Setup:
    def __init__(self, settings: OutputSettings | None = None) -> None:
        self.settings = settings or OutputSettings()
        self.clipboard = FakeClipboard()
        self.windows = FakeWindows()
        self.paster = FakePaster()
        self.sleeps: list[float] = []
        self.delivery = ResultDelivery(
            settings_provider=lambda: self.settings,
            clipboard=self.clipboard,
            windows=self.windows,
            paster=self.paster,
            sleep=self.sleeps.append,
        )


@pytest.fixture
def setup() -> Setup:
    return Setup()


# --------------------------------------------------------------------------- #
# Определение окна
# --------------------------------------------------------------------------- #


def test_capture_target_returns_active_window(setup: Setup) -> None:
    target = setup.delivery.capture_target()

    assert target is not None
    assert target.process_name == "notepad.exe"


def test_capture_target_tolerates_unknown_window(setup: Setup) -> None:
    setup.windows.target = None

    assert setup.delivery.capture_target() is None


def test_window_label_is_readable() -> None:
    assert WindowInfo(handle=1, title="main.py", process_name="Cursor.exe").label() == (
        "Cursor.exe — main.py"
    )
    assert WindowInfo(handle=1, process_name="Cursor.exe").label() == "Cursor.exe"
    assert WindowInfo(handle=7).label() == "окно 7"


# --------------------------------------------------------------------------- #
# Успешный путь
# --------------------------------------------------------------------------- #


def test_full_delivery_copies_and_pastes(setup: Setup) -> None:
    target = setup.delivery.capture_target()

    result = setup.delivery.deliver("готовый текст", target)

    assert result.copied is True
    assert result.pasted is True
    assert setup.clipboard.text == "готовый текст"
    assert setup.paster.paste_calls == ["ctrl_v"]
    assert setup.windows.activate_calls == 1
    assert "Вставлено" in result.message


def test_paste_delay_is_respected(setup: Setup) -> None:
    setup.settings.paste_delay_ms = 250

    setup.delivery.deliver("текст", setup.delivery.capture_target())

    assert setup.sleeps == [0.25]


def test_zero_delay_does_not_sleep(setup: Setup) -> None:
    setup.settings.paste_delay_ms = 0

    setup.delivery.deliver("текст", setup.delivery.capture_target())

    assert setup.sleeps == []


def test_shift_insert_method_is_used(setup: Setup) -> None:
    setup.settings.paste_method = "shift_insert"

    setup.delivery.deliver("текст", setup.delivery.capture_target())

    assert setup.paster.paste_calls == ["shift_insert"]


def test_unicode_method_types_the_text(setup: Setup) -> None:
    """Для окон, которые не читают буфер обмена."""
    setup.settings.paste_method = "unicode"

    setup.delivery.deliver("текст", setup.delivery.capture_target())

    assert setup.paster.typed == ["текст"]
    assert setup.paster.paste_calls == []


# --------------------------------------------------------------------------- #
# Отказы: текст обязан сохраниться в буфере
# --------------------------------------------------------------------------- #


def test_autopaste_disabled_only_copies(setup: Setup) -> None:
    setup.settings.auto_paste = False

    result = setup.delivery.deliver("текст", setup.delivery.capture_target())

    assert result.copied is True
    assert result.pasted is False
    assert setup.paster.paste_calls == []
    assert "буфер" in result.message


def test_busy_clipboard_is_reported_as_failure(setup: Setup) -> None:
    setup.clipboard.fail_on_set = True

    result = setup.delivery.deliver("текст", setup.delivery.capture_target())

    assert result.copied is False
    assert result.is_success is False
    assert "буфер обмена" in result.message


def test_unknown_window_still_copies(setup: Setup) -> None:
    result = setup.delivery.deliver("текст", None)

    assert result.copied is True
    assert result.pasted is False
    assert "неизвестно" in result.message
    assert setup.clipboard.text == "текст"


def test_closed_window_still_copies(setup: Setup) -> None:
    target = setup.delivery.capture_target()
    setup.windows.window_exists = False

    result = setup.delivery.deliver("текст", target)

    assert result.copied is True
    assert result.pasted is False
    assert "закрыто" in result.message


def test_switched_window_cancels_paste(setup: Setup) -> None:
    """Вставить надиктованное в чужое окно хуже, чем не вставить вовсе."""
    target = setup.delivery.capture_target()
    setup.windows.window_active = False

    result = setup.delivery.deliver("текст", target)

    assert result.pasted is False
    assert "Активно другое окно" in result.message
    assert setup.windows.activate_calls == 0


def test_switched_window_can_be_forced(setup: Setup) -> None:
    target = setup.delivery.capture_target()
    setup.windows.window_active = False
    setup.settings.confirm_if_window_changed = False

    result = setup.delivery.deliver("текст", target)

    assert result.pasted is True
    assert setup.windows.activate_calls == 1


def test_focus_refusal_is_explained(setup: Setup) -> None:
    target = setup.delivery.capture_target()
    setup.windows.can_activate = False

    result = setup.delivery.deliver("текст", target)

    assert result.copied is True
    assert result.pasted is False
    assert "фокус" in result.message
    assert setup.paster.paste_calls == []


def test_blocked_input_mentions_administrator(setup: Setup) -> None:
    """Самая частая причина молчаливого отказа SendInput."""
    target = setup.delivery.capture_target()
    setup.paster.succeed = False

    result = setup.delivery.deliver("текст", target)

    assert result.copied is True
    assert result.pasted is False
    assert "администратора" in result.message
    assert "буфере" in result.message


def test_empty_text_is_rejected(setup: Setup) -> None:
    result = setup.delivery.deliver("", setup.delivery.capture_target())

    assert result.copied is False
    assert setup.clipboard.set_calls == []


# --------------------------------------------------------------------------- #
# Восстановление буфера обмена
# --------------------------------------------------------------------------- #


def test_previous_clipboard_is_remembered_when_asked(setup: Setup) -> None:
    setup.settings.restore_clipboard = True
    setup.clipboard.text = "то, что было раньше"

    result = setup.delivery.deliver("новый текст", setup.delivery.capture_target())

    assert result.previous_clipboard == "то, что было раньше"


def test_previous_clipboard_is_not_read_by_default(setup: Setup) -> None:
    setup.clipboard.text = "то, что было раньше"

    result = setup.delivery.deliver("новый текст", setup.delivery.capture_target())

    assert result.previous_clipboard is None


def test_restore_clipboard_puts_the_old_text_back(setup: Setup) -> None:
    setup.settings.restore_clipboard = True
    setup.clipboard.text = "старое"
    result = setup.delivery.deliver("новое", setup.delivery.capture_target())

    assert setup.delivery.restore_clipboard(result.previous_clipboard) is True
    assert setup.clipboard.text == "старое"


def test_restore_without_saved_value_does_nothing(setup: Setup) -> None:
    assert setup.delivery.restore_clipboard(None) is False


def test_restore_keeps_what_user_copied_meanwhile(setup: Setup) -> None:
    setup.settings.restore_clipboard = True
    setup.clipboard.text = "старое"
    result = setup.delivery.deliver("новое", setup.delivery.capture_target())

    # Пользователь успел скопировать своё — возврат отменяется.
    setup.clipboard.text = "чужое, скопированное вручную"

    assert setup.delivery.restore_clipboard(result.previous_clipboard, "новое") is False
    assert setup.clipboard.text == "чужое, скопированное вручную"


def test_restore_works_while_our_text_is_still_in_clipboard(setup: Setup) -> None:
    setup.settings.restore_clipboard = True
    setup.clipboard.text = "старое"
    result = setup.delivery.deliver("новое", setup.delivery.capture_target())

    assert setup.delivery.restore_clipboard(result.previous_clipboard, "новое") is True
    assert setup.clipboard.text == "старое"
