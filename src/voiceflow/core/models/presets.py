"""Три пресета качества.

Пресет — это единственная ручка, которой пользователь балансирует качество,
скорость и требования к железу. Переключение меняет только конфигурацию:
какой движок распознавания брать, нужна ли языковая модель и держать ли её
постоянно в памяти. Код конвейера при этом не трогается.

Состав моделей каждого пресета задаётся не здесь, а в реестре
``config/models.toml`` полем ``presets`` — иначе список пришлось бы держать
в двух местах.
"""

from __future__ import annotations

from dataclasses import dataclass

from voiceflow.core.settings.schema import PRESETS, Settings


@dataclass(frozen=True, slots=True)
class PresetSpec:
    """Описание пресета для мастера и вкладки «Модели»."""

    id: str
    title: str
    summary: str
    #: Значение для ``[recognition] engine``.
    engine: str
    #: Нужна ли языковая модель для полировки, перевода и режима «Инструкция».
    use_llm: bool
    #: Держать ли языковую модель загруженной между запросами.
    keep_llm_loaded: bool
    #: Требования к машине — показываются пользователю до загрузки моделей.
    requirements: str
    #: Ожидаемое время от остановки записи до готового текста.
    latency: str


LIGHT = PresetSpec(
    id="light",
    title="Лёгкий",
    summary=(
        "GigaAM на процессоре, очистка правилами, языковая модель выключена. "
        "Режим «Инструкция» деградирует до структурирования по правилам."
    ),
    engine="gigaam",
    use_llm=False,
    keep_llm_loaded=False,
    requirements="4 ядра, 8 ГБ ОЗУ, видеокарта не нужна",
    latency="1-3 секунды",
)

STANDARD = PresetSpec(
    id="standard",
    title="Стандарт",
    summary=(
        "Движок подбирается по языку речи, языковая модель постоянно в памяти, "
        "перевод и режим «Инструкция» работают через неё."
    ),
    engine="auto",
    use_llm=True,
    keep_llm_loaded=True,
    requirements="6 ядер, 16 ГБ ОЗУ, видеокарта NVIDIA с 6 ГБ памяти",
    latency="2-4 секунды",
)

QUALITY = PresetSpec(
    id="quality",
    title="Качество",
    summary=(
        "Whisper для смешанной речи и языковая модель большего размера. "
        "Модели загружаются поочерёдно, поэтому обработка заметно дольше."
    ),
    engine="whisper",
    use_llm=True,
    # Модель 8B не помещается рядом с ASR на 6 ГБ видеопамяти,
    # поэтому её выгружаем между запросами.
    keep_llm_loaded=False,
    requirements="8 ГБ видеопамяти либо 32 ГБ ОЗУ для работы на процессоре",
    latency="5-10 секунд",
)

#: Пресеты в порядке возрастания требований.
PRESET_SPECS: dict[str, PresetSpec] = {
    LIGHT.id: LIGHT,
    STANDARD.id: STANDARD,
    QUALITY.id: QUALITY,
}

DEFAULT_PRESET = STANDARD.id


class UnknownPresetError(ValueError):
    """Пресета с таким идентификатором не существует."""


def get_preset(preset_id: str) -> PresetSpec:
    """Возвращает описание пресета."""
    spec = PRESET_SPECS.get(preset_id)
    if spec is None:
        raise UnknownPresetError(
            f"Неизвестный пресет «{preset_id}». Доступны: {', '.join(PRESET_SPECS)}"
        )
    return spec


def list_presets() -> list[PresetSpec]:
    """Пресеты в порядке отображения."""
    return [PRESET_SPECS[name] for name in PRESETS]


def apply_preset(settings: Settings, preset_id: str) -> list[str]:
    """Записывает пресет в настройки.

    Возвращает список изменений на понятном языке — мастер и вкладка «Модели»
    показывают его пользователю, чтобы переключение не было молчаливым.
    Настройки только меняются в памяти; сохранение остаётся за вызывающим.
    """
    spec = get_preset(preset_id)
    changes: list[str] = []

    if settings.recognition.preset != spec.id:
        changes.append(f"пресет: {settings.recognition.preset} -> {spec.id}")
        settings.recognition.preset = spec.id

    if settings.recognition.engine != spec.engine:
        changes.append(f"движок распознавания: {settings.recognition.engine} -> {spec.engine}")
        settings.recognition.engine = spec.engine

    if settings.processing.use_llm != spec.use_llm:
        changes.append("языковая модель: " + ("включена" if spec.use_llm else "выключена"))
        settings.processing.use_llm = spec.use_llm

    if settings.llm.keep_loaded != spec.keep_llm_loaded:
        changes.append(
            "языковая модель в памяти: "
            + ("постоянно" if spec.keep_llm_loaded else "выгружается между запросами")
        )
        settings.llm.keep_loaded = spec.keep_llm_loaded

    return changes


def matches(settings: Settings, preset_id: str) -> bool:
    """Соответствуют ли текущие настройки пресету целиком.

    Пользователь вправе изменить отдельные ключи после выбора пресета, и это
    не ошибка — интерфейс просто показывает пресет как изменённый.
    """
    spec = get_preset(preset_id)
    return (
        settings.recognition.preset == spec.id
        and settings.recognition.engine == spec.engine
        and settings.processing.use_llm == spec.use_llm
        and settings.llm.keep_loaded == spec.keep_llm_loaded
    )
