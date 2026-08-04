"""Доставка готового текста: буфер обмена и вставка в активное окно.

Порядок шагов зафиксирован планом и разобран по одному, потому что каждый
может не сработать по независимой причине:

1. окно запоминается в момент начала записи;
2. текст всегда попадает в буфер обмена — это единственный шаг, который
   обязан выполниться, иначе результат теряется;
3. при включённой автовставке проверяется, что окно ещё существует и активно;
4. фокус возвращается, выдерживается настраиваемая задержка;
5. посылается сочетание вставки.

Проверить факт вставки надёжно невозможно: приложение может её проглотить.
Поэтому сообщение пользователю формулируется честно — «вставлено» или
«не удалось вставить, текст в буфере».
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from voiceflow.core.settings.schema import OutputSettings
from voiceflow.platform.base import Clipboard, ForegroundWindows, Paster, WindowInfo

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    """Что удалось сделать с готовым текстом."""

    copied: bool
    pasted: bool
    message: str
    target: WindowInfo | None = None
    #: Предыдущее содержимое буфера, если его просили сохранить.
    previous_clipboard: str | None = None

    @property
    def is_success(self) -> bool:
        """Успех — это как минимум сохранённый текст."""
        return self.copied


class ResultDelivery:
    """Кладёт текст в буфер обмена и по возможности вставляет его."""

    def __init__(
        self,
        settings_provider: Callable[[], OutputSettings],
        clipboard: Clipboard,
        windows: ForegroundWindows,
        paster: Paster,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings_provider = settings_provider
        self._clipboard = clipboard
        self._windows = windows
        self._paster = paster
        self._sleep = sleep

    def capture_target(self) -> WindowInfo | None:
        """Запоминает окно, в которое пойдёт текст.

        Вызывается в начале записи: плашка фокус не забирает, поэтому
        активным остаётся то окно, в котором работает пользователь.
        """
        target = self._windows.current()
        if target is not None:
            logger.info("Целевое окно: %s", target.label())
        else:
            logger.info("Активное окно определить не удалось")
        return target

    def deliver(self, text: str, target: WindowInfo | None) -> DeliveryResult:
        """Выполняет всю цепочку доставки."""
        if not text:
            return DeliveryResult(copied=False, pasted=False, message="Пустой текст")

        settings = self._settings_provider()
        previous = self._clipboard.get_text() if settings.restore_clipboard else None

        if not self._clipboard.set_text(text):
            return DeliveryResult(
                copied=False,
                pasted=False,
                message="Не удалось записать текст в буфер обмена",
                target=target,
            )

        if not settings.auto_paste:
            return DeliveryResult(
                copied=True,
                pasted=False,
                message="Текст скопирован в буфер обмена",
                target=target,
                previous_clipboard=previous,
            )

        reason = self._blocking_reason(target, settings)
        if reason is not None:
            return DeliveryResult(
                copied=True,
                pasted=False,
                message=f"{reason}. Текст в буфере обмена",
                target=target,
                previous_clipboard=previous,
            )

        assert target is not None  # проверено в _blocking_reason
        if not self._windows.activate(target.handle):
            return DeliveryResult(
                copied=True,
                pasted=False,
                message=(
                    "Windows не разрешила вернуть фокус целевому окну. "
                    "Текст в буфере обмена"
                ),
                target=target,
                previous_clipboard=previous,
            )

        if settings.paste_delay_ms > 0:
            self._sleep(settings.paste_delay_ms / 1000.0)

        if not self._perform_paste(text, settings.paste_method):
            return DeliveryResult(
                copied=True,
                pasted=False,
                message=(
                    "Вставка не прошла: окно могло быть запущено от администратора. "
                    "Текст в буфере обмена"
                ),
                target=target,
                previous_clipboard=previous,
            )

        return DeliveryResult(
            copied=True,
            pasted=True,
            message=f"Вставлено в {target.label()}",
            target=target,
            previous_clipboard=previous,
        )

    def restore_clipboard(self, previous: str | None, expected: str | None = None) -> bool:
        """Возвращает прежнее содержимое буфера обмена.

        ``expected`` — текст, который мы туда положили. Если в буфере уже
        другое, пользователь успел скопировать что-то своё, и перетирать это
        нельзя: восстановление не важнее его работы.
        """
        if previous is None:
            return False
        if expected is not None and self._clipboard.get_text() != expected:
            logger.info("Буфер обмена изменился, прежнее содержимое не возвращаю")
            return False
        return self._clipboard.set_text(previous)

    # ------------------------------------------------------------------ #
    # Внутреннее
    # ------------------------------------------------------------------ #

    def _blocking_reason(
        self, target: WindowInfo | None, settings: OutputSettings
    ) -> str | None:
        """Причина, по которой вставлять нельзя. ``None`` — можно."""
        if target is None:
            return "Целевое окно неизвестно"
        if not self._windows.exists(target.handle):
            return "Целевое окно закрыто"
        if settings.confirm_if_window_changed and not self._windows.is_active(
            target.handle
        ):
            # Пользователь ушёл в другое окно: вставлять туда чужой текст опаснее,
            # чем не вставить вовсе.
            return "Активно другое окно, вставка отменена"
        return None

    def _perform_paste(self, text: str, method: str) -> bool:
        if method == "unicode":
            return self._paster.type_text(text)
        return self._paster.paste(method)
