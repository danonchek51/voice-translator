"""Связывание ядра с интерфейсом.

Контроллер знает и про ядро, и про виджеты, поэтому обратной зависимости
(ядро -> интерфейс) не возникает. Все обработчики выполняются в главном
потоке Qt: события ядра приходят сюда уже через :class:`UiBridge`.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QTimer, Slot

from voiceflow.app import AppContext
from voiceflow.core.asr.registry import TranscriberRegistry
from voiceflow.core.audio.capture import AudioCapture
from voiceflow.core.delivery import ResultDelivery
from voiceflow.core.diagnostics.logging import set_user_text_logging, setup_logging
from voiceflow.core.events import (
    ResultDelivered,
    SettingsChanged,
    TextProcessed,
    TranscriptReady,
)
from voiceflow.core.history import HistoryRepository
from voiceflow.core.llm.manager import LlmManager
from voiceflow.core.llm.polisher import LlmPolisher
from voiceflow.core.models import ModelManager
from voiceflow.core.models.presets import apply_preset
from voiceflow.core.pipeline import Pipeline
from voiceflow.core.state import AppState
from voiceflow.core.text.glossary import Glossary
from voiceflow.core.text.modes import STEPS, apply_step_enabled, describe, get_step
from voiceflow.core.text.processor import TextProcessor
from voiceflow.core.triggers import TriggerSource
from voiceflow.core.wake import WakeService
from voiceflow.platform.base import (
    create_hotkey_listener,
    create_mouse_listener,
    get_clipboard,
    get_foreground_windows,
    get_paster,
)
from voiceflow.ui import style, theme
from voiceflow.ui.bridge import UiBridge
from voiceflow.ui.notification import NotificationWindow
from voiceflow.ui.overlay import OverlayWindow
from voiceflow.ui.settings_window import (
    TAB_DIAGNOSTICS,
    TAB_GENERAL,
    TAB_HISTORY,
    SettingsWindow,
)
from voiceflow.ui.tray import TrayIcon
from voiceflow.ui.wizard import FirstRunWizard

logger = logging.getLogger(__name__)

#: Пауза перед записью нового положения плашки, чтобы не дёргать диск при перетаскивании.
POSITION_SAVE_DELAY_MS = 700

#: Как часто обновляется таймер длительности записи на плашке.
RECORDING_TIMER_INTERVAL_MS = 200

#: Сколько символов распознанного текста показывать в уведомлении.
PREVIEW_LIMIT = 300

#: Что делать при ошибке. Само сообщение говорит, что случилось, подсказка —
#: куда идти дальше: без неё окно с ошибкой оставляет человека в тупике.
ERROR_HINTS: dict[str, str] = {
    "asr": "Откройте настройки, вкладка «Модели», и загрузите модель распознавания.",
    "audio": "Проверьте микрофон на вкладке «Диагностика».",
    "output": (
        "Так бывает с окнами, запущенными от администратора, и с играми "
        "в полноэкранном режиме. Текст остался в буфере обмена."
    ),
    "text": "Обработка отключилась, распознанный текст не потерян.",
    "pipeline": "Подробности записаны в журнал: вкладка «Диагностика».",
}


class AppController(QObject):
    """Владелец подсистем времени выполнения."""

    def __init__(self, context: AppContext, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._listening = False

        self._capture = AudioCapture(context.bus)
        self._capture.set_gain(context.settings.audio.gain)

        self._transcribers = TranscriberRegistry(lambda: self._context.settings.recognition)
        self._delivery = ResultDelivery(
            settings_provider=lambda: self._context.settings.output,
            clipboard=get_clipboard(),
            windows=get_foreground_windows(),
            paster=get_paster(),
        )
        self._glossary = Glossary.load()
        for note in self._glossary.notes:
            logger.warning("Словарь замен: %s", note)

        self._llm = LlmManager(lambda: self._context.settings.llm)
        self._processor = TextProcessor(
            settings_provider=lambda: self._context.settings.processing,
            glossary_provider=lambda: self._glossary,
            polisher=LlmPolisher(
                client_provider=self._llm.client,
                timeout_provider=lambda: self._context.settings.llm.timeout_s,
            ),
        )
        self._pipeline = Pipeline(
            settings_provider=lambda: self._context.settings,
            bus=context.bus,
            state=context.state,
            capture=self._capture,
            transcribers=self._transcribers,
            delivery=self._delivery,
            processor=self._processor,
        )
        self._wake = WakeService(
            settings_provider=lambda: self._context.settings.activation,
            bus=context.bus,
            state=context.state,
            on_start=lambda: self._pipeline.handle_press(TriggerSource.VOICE),
            on_stop=self._pipeline.stop_recording,
        )
        self._wake_unsubscribe = self._capture.add_consumer(self._wake.on_audio)

        self._models = ModelManager()
        self._wizard: FirstRunWizard | None = None
        self._history = HistoryRepository(lambda: self._context.settings.history)
        self._settings_window: SettingsWindow | None = None

        # Метрики последней записи: событие обработки их не несёт, а истории
        # нужны длительность речи и движок распознавания.
        self._last_transcript: TranscriptReady | None = None
        self._processing_started_at = 0.0

        self._bridge = UiBridge(context.bus, parent=self)
        self._overlay = OverlayWindow(context.settings.overlay)
        self._tray = TrayIcon(parent=self)
        self._notifications = NotificationWindow()

        activation = context.settings.activation
        self._hotkey = create_hotkey_listener(
            activation.hotkey,
            on_press=lambda: self._pipeline.handle_press(TriggerSource.HOTKEY),
            on_release=lambda: self._pipeline.handle_release(TriggerSource.HOTKEY),
        )
        self._mouse = create_mouse_listener(
            activation.mouse_button,
            on_press=lambda: self._pipeline.handle_press(TriggerSource.MOUSE),
            on_release=lambda: self._pipeline.handle_release(TriggerSource.MOUSE),
        )

        self._position_timer = QTimer(self)
        self._position_timer.setSingleShot(True)
        self._position_timer.setInterval(POSITION_SAVE_DELAY_MS)
        self._position_timer.timeout.connect(self._save_settings)

        self._recording_timer = QTimer(self)
        self._recording_timer.setInterval(RECORDING_TIMER_INTERVAL_MS)
        self._recording_timer.timeout.connect(self._update_recording_timer)

        self._connect()

    # ------------------------------------------------------------------ #
    # Жизненный цикл
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """Показывает интерфейс, открывает микрофон и включает способы запуска."""
        if not TrayIcon.is_available():
            logger.warning("Системный трей недоступен: управление только через плашку")
        self._tray.show()
        self._tray.set_state(self._context.state.state)
        self._refresh_steps()

        if self._context.settings.overlay.visible:
            self._overlay.show_without_focus()
        self._tray.set_overlay_visible(self._overlay.isVisible())

        self._start_listening()
        self._start_input_listeners()
        self._wake.set_enabled(self._context.settings.activation.wake_enabled)
        self._ensure_llm_model_path()
        self._offer_first_run_wizard()
        # Модель поднимается сейчас, пока приложение свободно: иначе пауза
        # в пять-семь секунд придётся на конец первой записи.
        self._transcribers.preload()

    def shutdown(self) -> None:
        """Освобождает микрофон, снимает перехваты и сохраняет настройки."""
        self._recording_timer.stop()
        if self._position_timer.isActive():
            self._position_timer.stop()
            self._save_settings()

        self._hotkey.stop()
        self._mouse.stop()
        self._wake.set_enabled(False)
        self._wake.close()
        if self._wake_unsubscribe is not None:
            self._wake_unsubscribe()
            self._wake_unsubscribe = None
        self._pipeline.shutdown()
        self._llm.shutdown()
        self._history.close()
        self._capture.stop(reason="выход")
        self._bridge.dispose()
        self._tray.hide()
        self._overlay.close()
        self._notifications.close()
        if self._wizard is not None:
            self._wizard.close()
        if self._settings_window is not None:
            self._settings_window.close()

    def _start_input_listeners(self) -> None:
        """Резервные способы запуска обязаны работать всегда."""
        if not self._hotkey.start():
            logger.warning("Горячая клавиша недоступна: %s", self._hotkey.description)
        if self._context.settings.activation.mouse_button != "none" and not self._mouse.start():
            logger.warning("Кнопка мыши недоступна: %s", self._mouse.description)

    # ------------------------------------------------------------------ #
    # Подключение сигналов
    # ------------------------------------------------------------------ #

    def _connect(self) -> None:
        self._bridge.state_changed.connect(self._on_state_changed)
        self._bridge.level_changed.connect(self._on_level_changed)
        self._bridge.error_occurred.connect(self._on_error)
        self._bridge.notice_issued.connect(self._on_notice)
        self._bridge.device_changed.connect(self._on_device_changed)
        self._bridge.result_delivered.connect(self._on_result_delivered)

        self._tray.start_recording_requested.connect(self._on_tray_start)
        self._tray.stop_recording_requested.connect(self._on_tray_stop)
        self._tray.toggle_listening_requested.connect(self._toggle_listening)
        self._tray.toggle_overlay_requested.connect(self._toggle_overlay)
        self._tray.history_requested.connect(self._open_history)
        self._tray.settings_requested.connect(self._open_settings)
        self._tray.diagnostics_requested.connect(self._open_diagnostics)
        self._tray.step_toggled.connect(self._on_step_toggled)
        self._tray.preset_selected.connect(self._on_preset_selected)
        self._tray.quit_requested.connect(self._quit)

        self._bridge.transcript_ready.connect(self._on_transcript_ready)
        self._bridge.text_processed.connect(self._on_text_processed)

        self._overlay.clicked.connect(self._on_overlay_clicked)
        self._overlay.position_changed.connect(self._on_overlay_moved)
        self._overlay.context_menu_requested.connect(self._on_overlay_context_menu)

    # ------------------------------------------------------------------ #
    # Запуск записи
    # ------------------------------------------------------------------ #

    @Slot()
    def _on_tray_start(self) -> None:
        self._pipeline.handle_press(TriggerSource.TRAY)

    @Slot()
    def _on_tray_stop(self) -> None:
        self._pipeline.stop_recording()

    @Slot()
    def _on_overlay_clicked(self) -> None:
        self._pipeline.handle_press(TriggerSource.OVERLAY)

    def _update_recording_timer(self) -> None:
        self._overlay.set_timer_seconds(self._capture.recording_seconds)

    # ------------------------------------------------------------------ #
    # Прослушивание
    # ------------------------------------------------------------------ #

    def _start_listening(self) -> None:
        audio = self._context.settings.audio
        started = self._capture.start(device_id=audio.device_id, device_name=audio.device_name)
        self._set_listening_state(started)
        if started:
            self._remember_device()
        else:
            self._context.state.to(AppState.ERROR, detail="нет микрофона")

    def _stop_listening(self, reason: str) -> None:
        self._wake.set_enabled(False)
        self._capture.stop(reason=reason)
        self._set_listening_state(False)

    @Slot()
    def _toggle_listening(self) -> None:
        """Пауза прослушивания полностью закрывает поток, освобождая микрофон."""
        if self._listening:
            self._pipeline.cancel_recording(reason="пауза прослушивания")
            self._stop_listening(reason="пауза по запросу пользователя")
            self._context.state.to(AppState.PAUSED, detail="микрофон отключён")
        else:
            self._context.state.to(AppState.IDLE)
            self._start_listening()
            self._wake.set_enabled(self._context.settings.activation.wake_enabled)

    def _remember_device(self) -> None:
        """Запоминает выбранное устройство, чтобы найти его на другой машине."""
        device = self._capture.device
        if device is None:
            return
        audio = self._context.settings.audio
        if audio.device_name == device.name and audio.device_id == device.index:
            return
        audio.device_name = device.name
        audio.device_id = device.index
        self._schedule_save()

    # ------------------------------------------------------------------ #
    # Плашка
    # ------------------------------------------------------------------ #

    @Slot()
    def _toggle_overlay(self) -> None:
        if self._overlay.isVisible():
            self._overlay.hide()
            self._context.settings.overlay.visible = False
        else:
            self._overlay.show_without_focus()
            self._context.settings.overlay.visible = True
        self._tray.set_overlay_visible(self._overlay.isVisible())
        self._schedule_save()

    @Slot(int, int, str)
    def _on_overlay_moved(self, x: int, y: int, screen_name: str) -> None:
        overlay = self._context.settings.overlay
        overlay.x = x
        overlay.y = y
        overlay.screen_id = screen_name
        self._schedule_save()

    @Slot(QPoint)
    def _on_overlay_context_menu(self, position: QPoint) -> None:
        self._tray.menu.popup(position)

    # ------------------------------------------------------------------ #
    # События ядра
    # ------------------------------------------------------------------ #

    @Slot(object, object, str)
    def _on_state_changed(self, old: AppState, new: AppState, detail: str) -> None:
        self._overlay.set_state(new, detail)
        self._tray.set_state(new, detail)

        if new is AppState.RECORDING:
            self._recording_timer.start()
        else:
            self._recording_timer.stop()

    @Slot(float, float)
    def _on_level_changed(self, rms: float, peak: float) -> None:
        self._overlay.set_level(rms, peak)

    @Slot(object)
    def _on_result_delivered(self, event: ResultDelivered) -> None:
        preview = event.text[:PREVIEW_LIMIT]
        if len(event.text) > PREVIEW_LIMIT:
            preview += "…"

        if event.pasted:
            # Вставка видна сама по себе, но короткое подтверждение на плашке
            # снимает вопрос «сработало или нет», особенно когда текст ушёл
            # в окно, которого сейчас не видно.
            logger.info("%s", event.message)
            self._overlay.flash("Готово", theme.SUCCESS)
            return

        if event.copied:
            self._overlay.flash("В буфере", theme.WARNING)
            self._notifications.show_notice(
                event.message,
                "Текст в буфере обмена — вставьте его сочетанием Ctrl+V.",
            )
            return

        self._notifications.show_error(event.message, ERROR_HINTS.get("output", ""))

    @Slot(str, str, bool)
    def _on_error(self, source: str, message: str, recoverable: bool) -> None:
        logger.error("Ошибка в подсистеме %s: %s", source, message)
        # На плашке от такого сообщения остался бы обрубок, поэтому отдельное
        # окно: оно вмещает текст целиком и ждёт, пока его прочитают.
        self._notifications.show_error(message, ERROR_HINTS.get(source, ""))

    @Slot(str, str)
    def _on_notice(self, source: str, message: str) -> None:
        logger.info("%s: %s", source, message)
        self._notifications.show_notice(message)

    @Slot(str, bool, str)
    def _on_device_changed(self, device_name: str, active: bool, reason: str) -> None:
        if not active and self._listening:
            # Устройство пропало само: сообщаем и не делаем вид, что всё хорошо.
            self._set_listening_state(False)
            self._context.state.to(AppState.ERROR, detail="микрофон потерян")

    def _set_listening_state(self, listening: bool) -> None:
        """Одно место, где состояние микрофона попадает в трей и в настройки."""
        self._listening = listening
        self._tray.set_listening(listening)
        if self._settings_window is not None:
            self._settings_window.set_listening(listening)

    # ------------------------------------------------------------------ #
    # Настройки
    # ------------------------------------------------------------------ #

    def _schedule_save(self) -> None:
        self._position_timer.start()

    def _save_settings(self) -> None:
        notes = self._context.settings_store.save()
        for note in notes:
            logger.warning("Настройки: %s", note)
        self._context.bus.publish(SettingsChanged())

    # ------------------------------------------------------------------ #
    # Окно настроек
    # ------------------------------------------------------------------ #

    def _ensure_settings_window(self) -> SettingsWindow:
        if self._settings_window is None:
            window = SettingsWindow(
                self._context.settings_store,
                self._models,
                self._history,
                context_provider=lambda: self._context,
                capture_provider=lambda: self._capture,
                transcribers_provider=lambda: self._transcribers,
                processor_provider=lambda: self._processor,
                delivery_provider=lambda: self._delivery,
            )
            window.settings_saved.connect(self._on_settings_saved)
            window.appearance_previewed.connect(self._apply_appearance)
            window.closed.connect(self._restore_appearance)
            window.wizard_requested.connect(self._show_wizard)
            window.listening_toggle_requested.connect(self._toggle_listening)
            window.copy_requested.connect(self._copy_text)
            window.paste_requested.connect(self._paste_text)
            window.set_listening(self._listening)
            self._settings_window = window
        return self._settings_window

    @Slot()
    def _open_settings(self) -> None:
        self._ensure_settings_window().open_at(TAB_GENERAL)

    @Slot()
    def _open_history(self) -> None:
        self._ensure_settings_window().open_at(TAB_HISTORY)

    @Slot()
    def _open_diagnostics(self) -> None:
        self._ensure_settings_window().open_at(TAB_DIAGNOSTICS)

    @Slot()
    def _on_settings_saved(self) -> None:
        """Применяет то, что нельзя просто записать в файл."""
        settings = self._context.settings

        setup_logging(level=settings.system.log_level, console=False)
        set_user_text_logging(settings.system.log_user_text)

        self._capture.set_gain(settings.audio.gain)
        self._apply_appearance()
        self._refresh_steps()

        # Пресет и движок меняют набор моделей, кэш становится неверным.
        self._transcribers.invalidate()

        self._wake.reload_phrases()
        self._wake.set_enabled(settings.activation.wake_enabled and self._listening)
        self._restart_input_listeners()

        self._context.bus.publish(SettingsChanged())

    def _restart_input_listeners(self) -> None:
        """Горячая клавиша и кнопка мыши задаются при создании перехватчика."""
        self._hotkey.stop()
        self._mouse.stop()
        activation = self._context.settings.activation
        self._hotkey = create_hotkey_listener(
            activation.hotkey,
            on_press=lambda: self._pipeline.handle_press(TriggerSource.HOTKEY),
            on_release=lambda: self._pipeline.handle_release(TriggerSource.HOTKEY),
        )
        self._mouse = create_mouse_listener(
            activation.mouse_button,
            on_press=lambda: self._pipeline.handle_press(TriggerSource.MOUSE),
            on_release=lambda: self._pipeline.handle_release(TriggerSource.MOUSE),
        )
        self._start_input_listeners()

    @Slot(str)
    def _copy_text(self, text: str) -> None:
        if text and get_clipboard().set_text(text):
            self._tray.notify("История", "Текст скопирован в буфер обмена")

    @Slot(str)
    def _paste_text(self, text: str) -> None:
        if not text:
            return
        outcome = self._delivery.deliver(text, self._delivery.capture_target())
        self._tray.notify("История", outcome.message, error=not outcome.copied)

    # ------------------------------------------------------------------ #
    # История
    # ------------------------------------------------------------------ #

    @Slot(object)
    def _on_transcript_ready(self, event: object) -> None:
        if isinstance(event, TranscriptReady):
            self._last_transcript = event
            self._processing_started_at = time.monotonic()

    @Slot(object)
    def _on_text_processed(self, event: object) -> None:
        """Записывает результат в историю. Аудио не сохраняется никогда."""
        if not isinstance(event, TextProcessed):
            return

        transcript = self._last_transcript
        elapsed_ms = (
            int((time.monotonic() - self._processing_started_at) * 1000)
            if self._processing_started_at
            else 0
        )
        try:
            self._history.add(
                raw_text=event.raw,
                clean_text=event.cleaned,
                final_text=event.final,
                # В историю пишем применённые шаги через запятую: вкладка
                # разворачивает их в читаемую цепочку.
                mode=",".join(event.steps),
                language=transcript.language if transcript else "",
                engine_asr=transcript.engine if transcript else "",
                engine_llm="llm" if event.used_llm else "",
                duration_ms=int(transcript.audio_seconds * 1000) if transcript else 0,
                elapsed_ms=elapsed_ms,
            )
        except Exception:
            # История не критична: сбой записи не должен ломать вставку текста.
            logger.exception("Не удалось сохранить запись истории")

        self._last_transcript = None
        self._processing_started_at = 0.0
        if self._settings_window is not None and self._settings_window.isVisible():
            self._settings_window.history.reload()

    # ------------------------------------------------------------------ #
    # Модели
    # ------------------------------------------------------------------ #

    def _offer_first_run_wizard(self) -> None:
        """Показывает мастер, пока моделей выбранного пресета нет на диске."""
        preset = self._context.settings.recognition.preset
        if self._models.is_preset_ready(preset):
            return
        logger.info("Модели пресета «%s» не готовы, открываю мастер", preset)
        self._show_wizard()

    def _show_wizard(self) -> None:
        if self._wizard is None:
            wizard = FirstRunWizard(self._context.settings_store, self._models)
            wizard.preset_applied.connect(self._on_preset_applied)
            self._wizard = wizard
        self._wizard.show()
        self._wizard.raise_()

    @Slot(str, bool)
    def _on_step_toggled(self, step_id: str, enabled: bool) -> None:
        """Шаг переключён из меню трея — самое частое действие."""
        step = get_step(step_id)
        if step is None:
            return
        settings = self._context.settings
        current = bool(getattr(settings.processing, step.enabled_by, False))
        if current == enabled:
            return
        notes = apply_step_enabled(settings.processing, step_id, enabled)
        for note in self._context.settings_store.save(settings):
            logger.warning("Настройки: %s", note)
        logger.info("Шаг «%s»: %s", step.title, "включён" if enabled else "выключен")
        for note in notes:
            logger.info("Обработка: %s", note)
        self._refresh_steps()
        # Только синхронизируем поля: не активируем окно и не закрываем его.
        self._sync_settings_window()

    @Slot(str)
    def _on_preset_selected(self, preset: str) -> None:
        """Пресет выбран из меню трея."""
        settings = self._context.settings
        if settings.recognition.preset == preset:
            return
        changes = apply_preset(settings, preset)
        if not changes:
            return
        for note in self._context.settings_store.save(settings):
            logger.warning("Настройки: %s", note)
        logger.info("Пресет «%s»: %s", preset, "; ".join(changes))
        self._on_preset_applied(preset)
        self._refresh_steps()

    @Slot()
    def _restore_appearance(self) -> None:
        """Возвращает сохранённое оформление после закрытия окна настроек."""
        self._apply_appearance()

    @Slot(object)
    def _apply_appearance(self, settings=None) -> None:  # type: ignore[no-untyped-def]
        """Применяет оформление ко всему приложению на ходу.

        Один путь и для предпросмотра, и для сохранённых настроек: иначе
        предпросмотр показывал бы не то, что получится.
        """
        from PySide6.QtWidgets import QApplication

        target = settings if settings is not None else self._context.settings
        palette = theme.apply(target.appearance)

        app = QApplication.instance()
        if app is not None:
            style.apply_to(app, palette)

        self._overlay.apply_settings(target.overlay)
        self._overlay.set_indicator(target.appearance.indicator)
        self._overlay.update()

    def _refresh_steps(self) -> None:
        """Приводит меню трея и плашку в соответствие с настройками."""
        processing = self._context.settings.processing
        self._tray.set_steps(describe(processing))
        self._tray.set_step_states(
            {step.id: getattr(processing, step.enabled_by, False) for step in STEPS}
        )
        self._tray.set_preset(self._context.settings.recognition.preset)

        # Шаги через языковую модель без неё молча ничего не делают.
        llm_ready = self._models.is_llm_ready(self._context.settings.recognition.preset)
        for step in STEPS:
            if step.id == "clean":
                continue
            self._tray.set_step_available(
                step.id,
                llm_ready,
                "Нужна языковая модель: вкладка «Модели» в настройках.",
            )

    def _ensure_llm_model_path(self) -> None:
        """Указывает настройкам на скачанную языковую модель.

        Пользователь скачивает модель мастером, но в настройках путь к ней
        остаётся пустым, и перевод с режимом «Инструкция» молча отключаются.
        Проставляем сами; выбор пользователя не трогаем, если файл на месте.
        """
        settings = self._context.settings
        current = Path(settings.llm.model_path) if settings.llm.model_path else None
        if current is not None and current.is_file():
            return

        found = self._models.installed_llm_path(settings.recognition.preset)
        if found is None:
            return

        settings.llm.model_path = str(found)
        for note in self._context.settings_store.save(settings):
            logger.warning("Настройки: %s", note)
        self._llm.reload()
        logger.info("Языковая модель выбрана автоматически: %s", found.name)

    def _sync_settings_window(self) -> None:
        """Подтягивает значения в открытое окно настроек без смены фокуса.

        Переключение шагов из трея не должно прятать или активировать окно:
        иначе кажется, что «настройки закрылись после клика».
        """
        window = self._settings_window
        if window is None or not window.isVisible():
            return
        window.reload()

    @Slot(str)
    def _on_preset_applied(self, preset: str) -> None:
        """Смена пресета меняет набор моделей, поэтому кэш движков сбрасывается."""
        logger.info("Применён пресет «%s»", preset)
        self._ensure_llm_model_path()
        self._transcribers.invalidate()
        self._sync_settings_window()
        self._context.bus.publish(SettingsChanged(sections=frozenset({"recognition"})))

    @Slot()
    def _quit(self) -> None:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.quit()
