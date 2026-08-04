"""Мост между шиной событий ядра и сигналами Qt.

Ядро публикует события из рабочих потоков. Виджеты Qt можно трогать только
из главного потока, поэтому здесь события переупаковываются в сигналы:
Qt сам ставит их в очередь главного потока.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from voiceflow.core.events import (
    AudioDeviceChanged,
    AudioLevelChanged,
    ErrorOccurred,
    EventBus,
    NoticeIssued,
    RecordingFinished,
    RecordingStarted,
    ResultDelivered,
    SettingsChanged,
    StateChanged,
    TextProcessed,
    TranscriptReady,
)


class UiBridge(QObject):
    """Единственная точка, где события ядра превращаются в сигналы Qt."""

    #: старое состояние, новое состояние, пояснение
    state_changed = Signal(object, object, str)
    #: сглаженные rms и peak в диапазоне 0..1
    level_changed = Signal(float, float)
    #: источник, сообщение, восстановимая ли ошибка
    error_occurred = Signal(str, str, bool)
    #: источник, сообщение
    notice_issued = Signal(str, str)
    #: имя устройства, активно ли, причина
    device_changed = Signal(str, bool, str)
    #: изменённые разделы настроек
    settings_changed = Signal(object)
    #: началась запись, источник запуска
    recording_started = Signal(str)
    #: запись завершена: длительность, обрезана ли, отменена ли
    recording_finished = Signal(float, bool, bool)
    #: распознанный текст целиком
    transcript_ready = Signal(object)
    #: текст прошёл выбранный режим обработки
    text_processed = Signal(object)
    #: итоговый текст скопирован и, возможно, вставлен
    result_delivered = Signal(object)

    def __init__(self, bus: EventBus, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._bus = bus
        self._unsubscribes = [
            bus.subscribe(StateChanged, self._on_state),
            bus.subscribe(AudioLevelChanged, self._on_level),
            bus.subscribe(ErrorOccurred, self._on_error),
            bus.subscribe(NoticeIssued, self._on_notice),
            bus.subscribe(AudioDeviceChanged, self._on_device),
            bus.subscribe(SettingsChanged, self._on_settings),
            bus.subscribe(RecordingStarted, self._on_recording_started),
            bus.subscribe(RecordingFinished, self._on_recording_finished),
            bus.subscribe(TranscriptReady, self._on_transcript),
            bus.subscribe(TextProcessed, self._on_text_processed),
            bus.subscribe(ResultDelivered, self._on_result),
        ]

    def dispose(self) -> None:
        """Снимает подписки. Обязательно при закрытии приложения."""
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()

    def _on_state(self, event: StateChanged) -> None:
        self.state_changed.emit(event.old, event.new, event.detail)

    def _on_level(self, event: AudioLevelChanged) -> None:
        self.level_changed.emit(event.rms, event.peak)

    def _on_error(self, event: ErrorOccurred) -> None:
        self.error_occurred.emit(event.source, event.message, event.recoverable)

    def _on_notice(self, event: NoticeIssued) -> None:
        self.notice_issued.emit(event.source, event.message)

    def _on_device(self, event: AudioDeviceChanged) -> None:
        self.device_changed.emit(event.device_name, event.active, event.reason)

    def _on_settings(self, event: SettingsChanged) -> None:
        self.settings_changed.emit(event.sections)

    def _on_recording_started(self, event: RecordingStarted) -> None:
        self.recording_started.emit(event.source)

    def _on_recording_finished(self, event: RecordingFinished) -> None:
        self.recording_finished.emit(event.duration_seconds, event.truncated, event.cancelled)

    def _on_transcript(self, event: TranscriptReady) -> None:
        self.transcript_ready.emit(event)

    def _on_text_processed(self, event: TextProcessed) -> None:
        self.text_processed.emit(event)

    def _on_result(self, event: ResultDelivered) -> None:
        self.result_delivered.emit(event)
