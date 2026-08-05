"""Обратная связь плашки: подписи, подтверждение, сообщения.

Плашка шириной меньше двухсот точек. Длинное пояснение к состоянию — вроде
«Активно другое окно, вставка отменена» — превращалось там в обрубок, из
которого ничего не понять. Короткое остаётся на плашке, подробное уходит
в отдельное окно.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from voiceflow.core.settings.schema import OverlaySettings
from voiceflow.core.state import STATE_LABELS, AppState


@pytest.fixture(scope="module")
def qt_app() -> Iterator[object]:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


@pytest.fixture
def overlay(qt_app):  # type: ignore[no-untyped-def]
    from voiceflow.ui.overlay import OverlayWindow

    window = OverlayWindow(OverlaySettings())
    yield window
    window.close()


# --------------------------------------------------------------------------- #
# Подписи
# --------------------------------------------------------------------------- #


def test_long_detail_does_not_reach_the_label(overlay) -> None:  # type: ignore[no-untyped-def]
    """Именно так на плашке появлялся обрезанный текст."""
    overlay.set_state(AppState.IDLE, "Активно другое окно, вставка отменена")

    assert overlay._label.text() == STATE_LABELS[AppState.IDLE]


def test_long_detail_is_kept_in_the_tooltip(overlay) -> None:  # type: ignore[no-untyped-def]
    overlay.set_state(AppState.IDLE, "Активно другое окно, вставка отменена")

    assert "Активно другое окно" in overlay.toolTip()


def test_long_label_is_elided_not_chopped(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Именно обрезка по границе давала обрубок «Активно д»."""
    from PySide6.QtGui import QPixmap

    from voiceflow.ui.widgets.elided_label import ElidedLabel

    label = ElidedLabel("Очень длинная подпись, которая никак не поместится")
    label.resize(80, 16)

    assert label.is_elided
    # Полный текст сохраняется: он нужен подсказке.
    assert label.text().startswith("Очень длинная")
    # Отрисовка с сокращением не должна падать.
    label.render(QPixmap(label.size()))


def test_short_label_is_not_touched(qt_app) -> None:  # type: ignore[no-untyped-def]
    from voiceflow.ui.widgets.elided_label import ElidedLabel

    label = ElidedLabel("Готов к записи")
    label.resize(300, 16)

    assert not label.is_elided


def test_recording_shows_timer(overlay) -> None:  # type: ignore[no-untyped-def]
    overlay.set_state(AppState.RECORDING)
    overlay.set_timer_seconds(65)

    assert "1:05" in overlay._label.text()


def test_processing_shows_the_step(overlay) -> None:  # type: ignore[no-untyped-def]
    overlay.set_state(AppState.PROCESSING, "translate")

    assert overlay._label.text() == "Перевожу"


# --------------------------------------------------------------------------- #
# Подтверждение результата
# --------------------------------------------------------------------------- #


def test_flash_shows_result_then_returns(overlay) -> None:  # type: ignore[no-untyped-def]
    from voiceflow.ui import theme

    overlay.set_state(AppState.IDLE)
    overlay.flash("Готово", theme.SUCCESS, seconds=10)

    assert overlay._label.text() == "Готово"
    assert overlay._flash_color == theme.SUCCESS

    overlay._end_flash()

    assert overlay._label.text() == STATE_LABELS[AppState.IDLE]
    assert overlay._flash_color == ""


def test_flash_survives_state_change(overlay) -> None:  # type: ignore[no-untyped-def]
    """Конвейер возвращается в покой сразу, подтверждение должно устоять."""
    from voiceflow.ui import theme

    overlay.flash("Готово", theme.SUCCESS, seconds=10)
    overlay.set_state(AppState.IDLE)

    assert overlay._label.text() == "Готово"


def test_flash_timer_is_scheduled(overlay) -> None:  # type: ignore[no-untyped-def]
    from voiceflow.ui import theme

    overlay.flash("Готово", theme.SUCCESS, seconds=2)

    assert overlay._flash_timer.isActive()


# --------------------------------------------------------------------------- #
# Отдельное окно сообщений
# --------------------------------------------------------------------------- #


def test_error_window_keeps_the_whole_message(qt_app) -> None:  # type: ignore[no-untyped-def]
    from voiceflow.ui.notification import NotificationWindow

    window = NotificationWindow()
    message = "Ни один движок распознавания не готов. Откройте настройки и загрузите модель."
    window.show_error(message, "Вкладка «Модели».")

    assert window._body.text() == message
    assert window._hint.text() == "Вкладка «Модели»."
    window.close()


def test_error_waits_to_be_read(qt_app) -> None:  # type: ignore[no-untyped-def]
    from voiceflow.ui.notification import NotificationWindow

    window = NotificationWindow()
    window.show_error("что-то пошло не так")

    assert not window._timer.isActive(), "ошибка не должна исчезать сама"
    window.close()


def test_notice_disappears_on_its_own(qt_app) -> None:  # type: ignore[no-untyped-def]
    from voiceflow.ui.notification import NotificationWindow

    window = NotificationWindow()
    window.show_notice("текст в буфере обмена")

    assert window._timer.isActive()
    window.close()


def test_window_does_not_steal_focus(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Человек диктует в другое приложение: забрать фокус — сломать сценарий."""
    from PySide6.QtCore import Qt

    from voiceflow.ui.notification import NotificationWindow

    window = NotificationWindow()

    assert window.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    assert window.focusPolicy() == Qt.FocusPolicy.NoFocus
    window.close()


def test_every_error_source_has_a_hint() -> None:
    """Окно с ошибкой без подсказки оставляет человека в тупике."""
    from voiceflow.ui.controller import ERROR_HINTS

    for source in ("asr", "audio", "output", "text", "pipeline"):
        assert ERROR_HINTS.get(source), f"нет подсказки для источника {source}"
