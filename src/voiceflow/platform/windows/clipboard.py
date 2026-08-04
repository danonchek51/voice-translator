"""Буфер обмена Windows.

``OpenClipboard`` регулярно не срабатывает с первого раза: буфер в этот момент
может держать браузер, менеджер буфера обмена или удалённый рабочий стол.
Одиночная попытка означала бы потерю только что надиктованного текста, поэтому
здесь несколько повторов с короткой паузой.
"""

from __future__ import annotations

import logging
import time

import win32clipboard
import win32con

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
RETRY_DELAY_SECONDS = 0.05


class WindowsClipboard:
    """Реализация :class:`~voiceflow.platform.base.Clipboard` для Windows."""

    def set_text(self, text: str) -> bool:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                win32clipboard.OpenClipboard()
            except Exception:
                if attempt == MAX_ATTEMPTS:
                    logger.exception(
                        "Буфер обмена занят другим приложением, %s попыток исчерпано",
                        MAX_ATTEMPTS,
                    )
                    return False
                time.sleep(RETRY_DELAY_SECONDS)
                continue

            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
                return True
            except Exception:
                logger.exception("Не удалось записать текст в буфер обмена")
                return False
            finally:
                try:
                    win32clipboard.CloseClipboard()
                except Exception:
                    logger.debug("Повторное закрытие буфера обмена", exc_info=True)
        return False

    def get_text(self) -> str | None:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                win32clipboard.OpenClipboard()
            except Exception:
                if attempt == MAX_ATTEMPTS:
                    logger.debug("Буфер обмена недоступен для чтения")
                    return None
                time.sleep(RETRY_DELAY_SECONDS)
                continue

            try:
                if not win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                    return None
                value = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                return str(value) if value is not None else None
            except Exception:
                logger.debug("Не удалось прочитать буфер обмена", exc_info=True)
                return None
            finally:
                try:
                    win32clipboard.CloseClipboard()
                except Exception:
                    logger.debug("Повторное закрытие буфера обмена", exc_info=True)
        return None
