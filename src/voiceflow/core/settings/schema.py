"""Схема настроек.

Значения по умолчанию заданы прямо в dataclass — это гарантирует, что
приложение запустится даже без файла ``config/default_settings.toml``.
Заводской TOML накладывается поверх и позволяет менять умолчания при сборке,
а пользовательский файл накладывается последним.

Пользовательский файл хранит только отличия от заводских значений, поэтому
«сбросить раздел» — это просто удаление ключей.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any

#: Версия схемы. Увеличивается вместе с добавлением миграции.
CURRENT_SCHEMA_VERSION = 2


# --------------------------------------------------------------------------- #
# Допустимые значения перечислимых полей
# --------------------------------------------------------------------------- #

STOP_MODES = ("phrase", "same_phrase", "press_again", "hold")
MOUSE_BUTTONS = ("none", "x1", "x2", "middle")
PRESETS = ("light", "standard", "quality")
ASR_ENGINES = ("auto", "gigaam", "whisper")
LANGUAGE_MODES = ("auto", "fixed")
LLM_BACKENDS = ("builtin", "external")
PASTE_METHODS = ("ctrl_v", "shift_insert", "unicode")
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
HISTORY_LIMITS = (0, 10, 20, 50, 100)
THEMES = ("dark", "light")
INDICATORS = ("wave", "bars", "pulse")


@dataclass(slots=True)
class AudioSettings:
    #: Индекс устройства PortAudio. ``None`` — системное по умолчанию.
    device_id: int | None = None
    #: Имя устройства. При переносе на другой компьютер поиск идёт по имени.
    device_name: str = ""
    gain: float = 1.0


@dataclass(slots=True)
class ActivationSettings:
    #: Голосовая активация выключена по умолчанию: постоянно открытый микрофон
    #: должен быть осознанным выбором пользователя.
    wake_enabled: bool = False
    wake_phrase: str = "слушай сюда"
    stop_mode: str = "press_again"
    stop_phrase: str = "конец записи"
    #: Порог срабатывания детектора, 1 — самый строгий, 10 — самый чуткий.
    sensitivity: int = 5
    cooldown_ms: int = 2000
    hotkey: str = "<ctrl>+<alt>+d"
    mouse_button: str = "x2"
    #: Защитный лимит действует всегда, даже при выключенной остановке по тишине.
    max_record_seconds: int = 300
    silence_stop_enabled: bool = False
    silence_stop_seconds: float = 3.0


@dataclass(slots=True)
class RecognitionSettings:
    preset: str = "standard"
    engine: str = "auto"
    language_mode: str = "fixed"
    primary_language: str = "ru"


@dataclass(slots=True)
class ProcessingSettings:
    """Обработка — цепочка шагов, каждый включается своим флагом.

    Выбора режима нет: включённые шаги применяются по порядку. Если выключены
    все три, пользователь получает дословный текст.
    """

    use_llm: bool = True
    clean_enabled: bool = True
    #: Перевод и инструкция по умолчанию выключены: они меняют текст сильнее
    #: всего, и включать их пользователь должен осознанно.
    translate_enabled: bool = False
    prompt_mode_enabled: bool = False
    glossary_enabled: bool = True
    guard_strict: bool = True


@dataclass(slots=True)
class LlmSettings:
    backend: str = "builtin"
    #: Только петлевой адрес. Иное значение блокируется на уровне клиента.
    endpoint: str = "http://127.0.0.1:8079"
    model_path: str = ""
    n_gpu_layers: int = 999
    context_size: int = 4096
    #: На видеокарте ответ приходит за секунду-две, на процессоре — заметно
    #: дольше. Восьми секунд там не хватало, и обработка молча откатывалась
    #: к очистке правилами.
    timeout_s: float = 20.0
    keep_loaded: bool = True


@dataclass(slots=True)
class OutputSettings:
    auto_paste: bool = True
    paste_delay_ms: int = 150
    paste_method: str = "ctrl_v"
    restore_clipboard: bool = False
    confirm_if_window_changed: bool = True


@dataclass(slots=True)
class OverlaySettings:
    visible: bool = True
    #: ``None`` означает «положение ещё не выбрано, поставить по умолчанию».
    x: int | None = None
    y: int | None = None
    screen_id: str = ""
    scale: int = 100
    opacity: int = 90
    always_on_top: bool = True


@dataclass(slots=True)
class AppearanceSettings:
    """Оформление. Пустая строка означает «взять цвет из темы»."""

    theme: str = "dark"
    #: Цвет кнопок, выделений и волны.
    accent: str = ""
    #: Фон плашки: она висит поверх чужих окон, и ей идёт свой оттенок.
    overlay_color: str = ""
    #: Цвет волны, если он должен отличаться от акцента.
    wave_color: str = ""
    #: Как показывается уровень микрофона.
    indicator: str = "wave"


@dataclass(slots=True)
class HistorySettings:
    enabled: bool = True
    max_entries: int = 50


@dataclass(slots=True)
class SystemSettings:
    autostart: bool = False
    start_minimized: bool = True
    ui_language: str = "ru"
    log_level: str = "INFO"
    #: Разрешает писать распознанный текст в лог. Только для отладки.
    log_user_text: bool = False


@dataclass(slots=True)
class Settings:
    schema_version: int = CURRENT_SCHEMA_VERSION
    audio: AudioSettings = field(default_factory=AudioSettings)
    activation: ActivationSettings = field(default_factory=ActivationSettings)
    recognition: RecognitionSettings = field(default_factory=RecognitionSettings)
    processing: ProcessingSettings = field(default_factory=ProcessingSettings)
    llm: LlmSettings = field(default_factory=LlmSettings)
    output: OutputSettings = field(default_factory=OutputSettings)
    overlay: OverlaySettings = field(default_factory=OverlaySettings)
    appearance: AppearanceSettings = field(default_factory=AppearanceSettings)
    history: HistorySettings = field(default_factory=HistorySettings)
    system: SystemSettings = field(default_factory=SystemSettings)


#: Имена разделов в порядке отображения в интерфейсе.
SECTION_NAMES: tuple[str, ...] = tuple(
    f.name for f in fields(Settings) if f.name != "schema_version"
)


# --------------------------------------------------------------------------- #
# Преобразование в словарь и обратно
# --------------------------------------------------------------------------- #


def to_dict(settings: Settings) -> dict[str, Any]:
    """Полный словарь настроек, пригодный для записи в TOML."""
    return dataclasses.asdict(settings)


def from_dict(data: dict[str, Any]) -> Settings:
    """Собирает :class:`Settings`, игнорируя неизвестные ключи.

    Неизвестные ключи не теряются: их сохраняет :mod:`~voiceflow.core.settings.store`,
    работая с исходным словарём отдельно.
    """
    settings = Settings()
    version = data.get("schema_version")
    if isinstance(version, int):
        settings.schema_version = version

    for section_field in fields(Settings):
        if section_field.name == "schema_version":
            continue
        raw_section = data.get(section_field.name)
        if not isinstance(raw_section, dict):
            continue
        section_obj = getattr(settings, section_field.name)
        _apply_section(section_obj, raw_section)
    return settings


def _apply_section(section_obj: Any, raw: dict[str, Any]) -> None:
    for f in fields(section_obj):
        if f.name not in raw:
            continue
        value = raw[f.name]
        coerced = _coerce(value, f.type)
        if coerced is not _UNSET:
            setattr(section_obj, f.name, coerced)


class _Unset:
    __slots__ = ()


_UNSET = _Unset()


def _coerce(value: Any, annotation: Any) -> Any:
    """Приводит значение из TOML к типу поля. Возвращает ``_UNSET`` при несовпадении."""
    text = annotation if isinstance(annotation, str) else getattr(annotation, "__name__", "")

    optional = "None" in text
    if value is None:
        return None if optional else _UNSET

    if "bool" in text:
        return bool(value) if isinstance(value, bool) else _UNSET
    if "int" in text and "float" not in text:
        if isinstance(value, bool):
            return _UNSET
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return _UNSET
    if "float" in text:
        if isinstance(value, bool):
            return _UNSET
        if isinstance(value, int | float):
            return float(value)
        return _UNSET
    if "str" in text:
        return value if isinstance(value, str) else _UNSET
    return _UNSET


# --------------------------------------------------------------------------- #
# Проверка значений
# --------------------------------------------------------------------------- #


def validate(settings: Settings) -> list[str]:
    """Чинит выходящие за границы значения и возвращает список замечаний.

    Настройки не должны ронять приложение: любое неверное значение заменяется
    заводским, а пользователь получает понятное сообщение.
    """
    notes: list[str] = []
    defaults = Settings()

    def enum_field(section: Any, name: str, allowed: tuple[str, ...], section_name: str) -> None:
        value = getattr(section, name)
        if value not in allowed:
            fallback = getattr(getattr(defaults, section_name), name)
            notes.append(
                f"{section_name}.{name}: значение {value!r} недопустимо, "
                f"использую {fallback!r}"
            )
            setattr(section, name, fallback)

    def colour_field(section: Any, name: str, section_name: str) -> None:
        """Цвет вида ``#rrggbb``. Пустая строка означает «взять из темы»."""
        value = str(getattr(section, name) or "")
        if not value:
            return
        ok = value.startswith("#") and len(value) == 7
        if ok:
            try:
                int(value[1:], 16)
            except ValueError:
                ok = False
        if not ok:
            notes.append(
                f"{section_name}.{name}: {value!r} не похоже на цвет, беру из темы"
            )
            setattr(section, name, "")

    def clamp(section: Any, name: str, low: float, high: float, section_name: str) -> None:
        value = getattr(section, name)
        if value < low or value > high:
            clamped = min(max(value, low), high)
            clamped = type(value)(clamped)
            notes.append(
                f"{section_name}.{name}: значение {value} вне диапазона "
                f"{low}..{high}, использую {clamped}"
            )
            setattr(section, name, clamped)

    enum_field(settings.activation, "stop_mode", STOP_MODES, "activation")
    enum_field(settings.activation, "mouse_button", MOUSE_BUTTONS, "activation")
    clamp(settings.activation, "sensitivity", 1, 10, "activation")
    clamp(settings.activation, "cooldown_ms", 0, 10_000, "activation")
    clamp(settings.activation, "max_record_seconds", 10, 3600, "activation")
    clamp(settings.activation, "silence_stop_seconds", 1.0, 30.0, "activation")

    enum_field(settings.appearance, "theme", THEMES, "appearance")
    enum_field(settings.appearance, "indicator", INDICATORS, "appearance")
    for name in ("accent", "overlay_color", "wave_color"):
        colour_field(settings.appearance, name, "appearance")

    enum_field(settings.recognition, "preset", PRESETS, "recognition")
    enum_field(settings.recognition, "engine", ASR_ENGINES, "recognition")
    enum_field(settings.recognition, "language_mode", LANGUAGE_MODES, "recognition")

    enum_field(settings.llm, "backend", LLM_BACKENDS, "llm")
    clamp(settings.llm, "context_size", 512, 131_072, "llm")
    clamp(settings.llm, "timeout_s", 1.0, 300.0, "llm")
    clamp(settings.llm, "n_gpu_layers", 0, 999, "llm")

    enum_field(settings.output, "paste_method", PASTE_METHODS, "output")
    clamp(settings.output, "paste_delay_ms", 0, 5000, "output")

    clamp(settings.overlay, "scale", 75, 150, "overlay")
    clamp(settings.overlay, "opacity", 30, 100, "overlay")

    if settings.history.max_entries not in HISTORY_LIMITS:
        nearest = min(HISTORY_LIMITS, key=lambda x: abs(x - settings.history.max_entries))
        notes.append(
            f"history.max_entries: значение {settings.history.max_entries} "
            f"не входит в набор {HISTORY_LIMITS}, использую {nearest}"
        )
        settings.history.max_entries = nearest

    enum_field(settings.system, "log_level", LOG_LEVELS, "system")

    clamp(settings.audio, "gain", 0.1, 10.0, "audio")

    if not settings.activation.wake_phrase.strip():
        notes.append("activation.wake_phrase: пустая фраза, использую заводскую")
        settings.activation.wake_phrase = defaults.activation.wake_phrase

    if settings.activation.stop_mode == "phrase" and not settings.activation.stop_phrase.strip():
        notes.append("activation.stop_phrase: пустая фраза, использую заводскую")
        settings.activation.stop_phrase = defaults.activation.stop_phrase

    # Перевод и «Инструкция» вместе в истории пользователя давали кашу:
    # модель повторяла шаблон вместо текста. Оставляем инструкцию.
    if (
        settings.processing.translate_enabled
        and settings.processing.prompt_mode_enabled
    ):
        settings.processing.translate_enabled = False
        notes.append(
            "processing: перевод и «Инструкция для AI» нельзя включать вместе, "
            "перевод выключен"
        )

    return notes


def diff_from_defaults(settings: Settings, defaults: Settings) -> dict[str, Any]:
    """Разреженный словарь: только отличия от заводских значений."""
    result: dict[str, Any] = {"schema_version": settings.schema_version}
    for section_field in fields(Settings):
        name = section_field.name
        if name == "schema_version":
            continue
        current = getattr(settings, name)
        base = getattr(defaults, name)
        section_diff = {
            f.name: getattr(current, f.name)
            for f in fields(current)
            if getattr(current, f.name) != getattr(base, f.name)
        }
        if section_diff:
            result[name] = section_diff
    return result


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Рекурсивно накладывает ``overlay`` на копию ``base``."""
    merged = dict(base)
    for key, value in overlay.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = deep_merge(existing, value)
        else:
            merged[key] = value
    return merged


def is_settings_dataclass(obj: Any) -> bool:
    return is_dataclass(obj) and not isinstance(obj, type)
