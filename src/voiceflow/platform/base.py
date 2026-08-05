"""Интерфейсы платформозависимых операций.

Ядро и интерфейс работают только с этими протоколами. Реализации живут в
``voiceflow.platform.windows`` и ``voiceflow.platform.macos``, а выбираются
функцией :func:`get_platform`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WindowInfo:
    """Окно, в которое нужно вернуть текст."""

    handle: int
    title: str = ""
    process_name: str = ""

    def label(self) -> str:
        if self.process_name and self.title:
            return f"{self.process_name} — {self.title}"
        return self.process_name or self.title or f"окно {self.handle}"


@runtime_checkable
class WindowStyler(Protocol):
    """Тонкая настройка окна средствами операционной системы."""

    def make_non_activating(self, window_handle: int) -> bool:
        """Запрещает окну забирать фокус у активного приложения.

        Флагов Qt на Windows недостаточно: без ``WS_EX_NOACTIVATE`` плашка
        всё равно перехватывает фокус при щелчке. Возвращает ``False``, если
        система не поддерживает такую настройку.
        """
        ...

    def exclude_from_taskbar(self, window_handle: int) -> bool:
        """Убирает окно с панели задач и из переключателя окон."""
        ...


@runtime_checkable
class InputListener(Protocol):
    """Глобальный слушатель клавиатуры или мыши.

    Сообщает только о нажатии и отпускании: что с этим делать, решает
    :class:`~voiceflow.core.triggers.TriggerCoordinator`.

    Обратные вызовы приходят из отдельного потока слушателя, поэтому
    обработчик обязан быть потокобезопасным и быстрым.
    """

    def start(self) -> bool:
        """Устанавливает перехват. ``False`` — не удалось."""
        ...

    def stop(self) -> None: ...

    @property
    def is_running(self) -> bool: ...

    @property
    def description(self) -> str:
        """Человекочитаемое описание для настроек и диагностики."""
        ...


@runtime_checkable
class Clipboard(Protocol):
    """Буфер обмена.

    Реализация обязана переживать временную занятость буфера другим
    процессом: текст не должен теряться из-за чужого окна.
    """

    def set_text(self, text: str) -> bool: ...

    def get_text(self) -> str | None: ...


@runtime_checkable
class ForegroundWindows(Protocol):
    """Работа с активным окном."""

    def current(self) -> WindowInfo | None:
        """Окно, активное прямо сейчас."""
        ...

    def exists(self, handle: int) -> bool: ...

    def is_active(self, handle: int) -> bool: ...

    def activate(self, handle: int) -> bool:
        """Возвращает окну фокус. ``False`` — система не разрешила."""
        ...


@runtime_checkable
class Paster(Protocol):
    """Отправка нажатий в активное окно."""

    def paste(self, method: str) -> bool:
        """Посылает сочетание вставки: ``ctrl_v`` или ``shift_insert``."""
        ...

    def type_text(self, text: str) -> bool:
        """Печатает текст посимвольно для окон, игнорирующих буфер обмена."""
        ...


@runtime_checkable
class Autostart(Protocol):
    """Запуск приложения вместе с системой.

    На macOS это будет LaunchAgent, поэтому способ спрятан за интерфейсом:
    настройки знают только «включено» и «выключено».
    """

    @property
    def is_supported(self) -> bool: ...

    @property
    def description(self) -> str:
        """Куда именно записывается автозапуск. Показывается в диагностике."""
        ...

    def is_enabled(self) -> bool: ...

    def set_enabled(self, enabled: bool) -> bool:
        """``False`` — система не дала изменить настройку."""
        ...


class NullClipboard:
    """Заглушка: хранит текст в памяти, чтобы тесты и Linux не падали."""

    def __init__(self) -> None:
        self._text: str | None = None

    def set_text(self, text: str) -> bool:
        self._text = text
        return True

    def get_text(self) -> str | None:
        return self._text


class NullForegroundWindows:
    def current(self) -> WindowInfo | None:
        return None

    def exists(self, handle: int) -> bool:
        return False

    def is_active(self, handle: int) -> bool:
        return False

    def activate(self, handle: int) -> bool:
        return False


class NullPaster:
    def paste(self, method: str) -> bool:
        return False

    def type_text(self, text: str) -> bool:
        return False


class NullWindowStyler:
    """Заглушка для систем без специальной обработки окон."""

    def make_non_activating(self, window_handle: int) -> bool:
        return False

    def exclude_from_taskbar(self, window_handle: int) -> bool:
        return False


class NullAutostart:
    """Заглушка для систем, где автозапуск ещё не реализован."""

    @property
    def is_supported(self) -> bool:
        return False

    @property
    def description(self) -> str:
        return "автозапуск недоступен на этой системе"

    def is_enabled(self) -> bool:
        return False

    def set_enabled(self, enabled: bool) -> bool:
        return False


class NullInputListener:
    """Заглушка для систем без глобального перехвата ввода."""

    def __init__(self, description: str = "недоступно") -> None:
        self._description = description

    def start(self) -> bool:
        return False

    def stop(self) -> None:
        return None

    @property
    def is_running(self) -> bool:
        return False

    @property
    def description(self) -> str:
        return self._description


def get_window_styler() -> WindowStyler:
    """Возвращает реализацию для текущей системы."""
    import sys

    if sys.platform == "win32":
        try:
            from voiceflow.platform.windows.window_style import WindowsWindowStyler

            return WindowsWindowStyler()
        except Exception:
            logger.exception("Не удалось загрузить настройку окон для Windows")
    return NullWindowStyler()


def create_hotkey_listener(
    combination: str,
    on_press: Callable[[], None],
    on_release: Callable[[], None],
) -> InputListener:
    """Слушатель глобальной горячей клавиши для текущей системы.

    На macOS понадобится отдельная реализация: там перехват требует
    разрешения Accessibility, которое нужно запрашивать у пользователя.
    """
    import sys

    if sys.platform == "win32":
        try:
            from voiceflow.platform.windows.hotkeys import HotkeyListener

            return HotkeyListener(combination, on_press, on_release)
        except Exception:
            logger.exception("Глобальные горячие клавиши недоступны")
    return NullInputListener("горячие клавиши недоступны на этой системе")


def create_mouse_listener(
    button: str,
    on_press: Callable[[], None],
    on_release: Callable[[], None],
) -> InputListener:
    """Слушатель кнопки мыши для текущей системы."""
    import sys

    if sys.platform == "win32":
        try:
            from voiceflow.platform.windows.mouse import MouseButtonListener

            return MouseButtonListener(button, on_press, on_release)
        except Exception:
            logger.exception("Запуск кнопкой мыши недоступен")
    return NullInputListener("кнопка мыши недоступна на этой системе")


def get_clipboard() -> Clipboard:
    import sys

    if sys.platform == "win32":
        try:
            from voiceflow.platform.windows.clipboard import WindowsClipboard

            return WindowsClipboard()
        except Exception:
            logger.exception("Буфер обмена Windows недоступен")
    return NullClipboard()


def get_foreground_windows() -> ForegroundWindows:
    import sys

    if sys.platform == "win32":
        try:
            from voiceflow.platform.windows.foreground import WindowsForegroundWindows

            return WindowsForegroundWindows()
        except Exception:
            logger.exception("Определение активного окна недоступно")
    return NullForegroundWindows()


def get_paster() -> Paster:
    import sys

    if sys.platform == "win32":
        try:
            from voiceflow.platform.windows.paste import WindowsPaster

            return WindowsPaster()
        except Exception:
            logger.exception("Автоматическая вставка недоступна")
    return NullPaster()


def get_autostart() -> Autostart:
    """Управление автозапуском для текущей системы."""
    import sys

    if sys.platform == "win32":
        try:
            from voiceflow.platform.windows.autostart import WindowsAutostart

            return WindowsAutostart()
        except Exception:
            logger.exception("Автозапуск недоступен")
    return NullAutostart()


@dataclass(frozen=True, slots=True)
class HardwareInfo:
    """Что удалось узнать о машине. Нули означают «выяснить не удалось»."""

    cores: int = 0
    memory_bytes: int = 0
    gpu_name: str = ""
    gpu_memory_bytes: int = 0

    @property
    def memory_gb(self) -> float:
        return self.memory_bytes / 1024**3

    @property
    def gpu_memory_gb(self) -> float:
        return self.gpu_memory_bytes / 1024**3

    @property
    def has_gpu(self) -> bool:
        return bool(self.gpu_name)


def probe_hardware() -> HardwareInfo:
    """Собирает сведения о машине для подбора конфигурации."""
    import os
    import sys

    cores = os.cpu_count() or 0
    if sys.platform != "win32":
        return HardwareInfo(cores=cores)

    try:
        from voiceflow.platform.windows.hardware import total_memory_bytes, video_adapter

        gpu_name, gpu_memory = video_adapter()
        return HardwareInfo(
            cores=cores,
            memory_bytes=total_memory_bytes(),
            gpu_name=gpu_name,
            gpu_memory_bytes=gpu_memory,
        )
    except Exception:
        logger.exception("Не удалось определить характеристики машины")
        return HardwareInfo(cores=cores)


def lower_current_thread_priority() -> bool:
    """Понижает приоритет текущего потока.

    Распознавание идёт, пока человек продолжает работать в другом окне. Даже
    ограниченное числом ядер, оно соперничает за процессор с отрисовкой
    рабочего стола, и указатель начинает дёргаться. Фоновой работе уступать
    правильно: задержка в доли секунды незаметна, рывки заметны сразу.

    Возвращает ``False``, если система такого не умеет — это не ошибка.
    """
    import sys

    if sys.platform != "win32":
        return False
    try:
        import ctypes

        # -1 — псевдодескриптор текущего потока, -1 в приоритете означает
        # BELOW_NORMAL: поток уступает интерфейсу, но не голодает.
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        return bool(kernel32.SetThreadPriority(kernel32.GetCurrentThread(), -1))
    except Exception:
        logger.debug("Не удалось понизить приоритет потока", exc_info=True)
        return False
