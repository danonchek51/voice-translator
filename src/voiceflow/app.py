"""Сборка приложения: пути, логи, настройки, шина событий, машина состояний.

Здесь нет ни Qt, ни Win32 — только контекст, которым пользуются и интерфейс,
и тесты. Слои интерфейса и платформы подключаются поверх этого контекста.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from voiceflow import __version__, paths
from voiceflow.core.diagnostics.logging import set_user_text_logging, setup_logging
from voiceflow.core.events import EventBus, StateChanged
from voiceflow.core.modelstore import configure_offline_cache
from voiceflow.core.settings import Settings, SettingsStore
from voiceflow.core.state import AppState, StateMachine

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AppContext:
    """Общий контекст приложения, передаваемый всем подсистемам."""

    settings_store: SettingsStore
    bus: EventBus
    state: StateMachine
    log_file: Path | None

    @property
    def settings(self) -> Settings:
        return self.settings_store.settings


def build_context(console_logging: bool = True) -> AppContext:
    """Создаёт контекст: каталоги, логи, настройки, шина, состояние."""
    paths.ensure_user_dirs()

    # Модели ищутся только на диске: основной режим не должен ходить в сеть.
    configure_offline_cache()

    # Логи нужны до чтения настроек, чтобы записать замечания загрузки.
    log_file = setup_logging(level="INFO", console=console_logging)

    store = SettingsStore()
    settings = store.load()

    # Уровень логирования применяем уже из настроек.
    log_file = setup_logging(level=settings.system.log_level, console=console_logging)
    set_user_text_logging(settings.system.log_user_text)

    logger.info("VoiceFlow %s, portable=%s", __version__, paths.is_portable())
    for note in store.notes:
        logger.warning("Настройки: %s", note)

    bus = EventBus()
    state = StateMachine()

    def on_state_change(old: AppState, new: AppState, detail: str) -> None:
        bus.publish(StateChanged(old=old, new=new, detail=detail))

    state.add_listener(on_state_change)

    return AppContext(settings_store=store, bus=bus, state=state, log_file=log_file)


def environment_report(context: AppContext | None = None) -> dict[str, str]:
    """Сводка окружения для вкладки диагностики и для отчётов об ошибках."""
    import platform as platform_module
    import sys

    report: dict[str, str] = {
        "version": __version__,
        "python": sys.version.split()[0],
        "platform": f"{platform_module.system()} {platform_module.release()}",
        "frozen": str(paths.is_frozen()),
    }
    report.update(paths.describe())
    if context is not None:
        report["state"] = context.state.state.value
        report["preset"] = context.settings.recognition.preset
        report["log_file"] = str(context.log_file) if context.log_file else "-"
    return report
