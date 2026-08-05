"""Запуск графического интерфейса."""

from __future__ import annotations

import logging
import sys

from voiceflow.app import AppContext

logger = logging.getLogger(__name__)


def run_ui(context: AppContext) -> int:
    """Создаёт приложение Qt и передаёт управление циклу событий."""
    guard = _single_instance_guard()
    if guard is not None and not guard.acquire():
        logger.error("VoiceFlow уже запущен")
        print("VoiceFlow уже запущен. Иконка находится в системном трее.")
        return 1

    from PySide6.QtWidgets import QApplication

    from voiceflow.ui import style
    from voiceflow.ui.controller import AppController

    app = QApplication(sys.argv)
    app.setApplicationName("VoiceFlow")
    app.setApplicationDisplayName("VoiceFlow")
    # Приложение живёт в трее: закрытие окна настроек не должно его завершать.
    app.setQuitOnLastWindowClosed(False)

    from voiceflow.ui import icons

    app.setWindowIcon(icons.app_icon())
    style.apply_to(app)

    controller = AppController(context)
    controller.start()
    try:
        code = app.exec()
    finally:
        controller.shutdown()
        if guard is not None:
            guard.release()
    return int(code)


def _single_instance_guard():  # type: ignore[no-untyped-def]
    if sys.platform != "win32":
        return None
    try:
        from voiceflow.platform.windows.single_instance import SingleInstanceGuard

        return SingleInstanceGuard()
    except Exception:
        logger.exception("Проверка единственного экземпляра недоступна")
        return None
