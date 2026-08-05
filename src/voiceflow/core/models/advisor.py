"""Подбор конфигурации под машину.

Человек, впервые открывший приложение, не обязан знать, потянет ли его
компьютер модель на четыре миллиарда параметров. Здесь по характеристикам
машины выбирается пресет и объясняется, почему именно он.

Правило простое и намеренно осторожное: предлагаем то, что точно будет
работать быстро, а не то, что теоретически запустится. Разочарование от
медленной работы обходится дороже, чем чуть меньшее качество.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from voiceflow.core.models.presets import PRESET_SPECS, get_preset

#: Языковая модель на четыре миллиарда параметров занимает около трёх
#: гигабайт видеопамяти в четырёхбитном сжатии, рядом с ней должно остаться
#: место под распознавание.
MIN_VRAM_FOR_LLM_GB = 5.0

#: Без видеокарты языковая модель считается на процессоре и требует памяти
#: и ядер: иначе ответ приходит десятки секунд.
MIN_RAM_FOR_CPU_LLM_GB = 15.0
MIN_CORES_FOR_CPU_LLM = 8

#: Ниже этого объёма памяти тяжёлые модели брать нельзя вовсе.
MIN_RAM_GB = 7.0


@dataclass(frozen=True, slots=True)
class Recommendation:
    """Что предложить и почему."""

    preset: str
    #: Короткое объяснение выбора для мастера и вкладки «Распознавание».
    reason: str
    #: Что именно нашлось на машине — показывается человеку как есть.
    findings: tuple[str, ...] = field(default_factory=tuple)
    #: Замечания: чего не хватает и что это меняет.
    limits: tuple[str, ...] = field(default_factory=tuple)

    @property
    def title(self) -> str:
        return get_preset(self.preset).title


def describe_machine(hardware) -> tuple[str, ...]:  # type: ignore[no-untyped-def]
    """Человеческое описание машины."""
    parts: list[str] = []
    if hardware.cores:
        parts.append(f"{hardware.cores} логических ядер")
    if hardware.memory_bytes:
        parts.append(f"{hardware.memory_gb:.0f} ГБ оперативной памяти")
    if hardware.gpu_name:
        if hardware.gpu_memory_bytes:
            parts.append(f"{hardware.gpu_name}, {hardware.gpu_memory_gb:.0f} ГБ видеопамяти")
        else:
            parts.append(hardware.gpu_name)
    else:
        parts.append("отдельная видеокарта не найдена")
    return tuple(parts)


def recommend(hardware) -> Recommendation:  # type: ignore[no-untyped-def]
    """Подбирает пресет под машину."""
    findings = describe_machine(hardware)
    limits: list[str] = []

    cores = hardware.cores or 4
    ram = hardware.memory_gb
    vram = hardware.gpu_memory_gb

    # Ничего не удалось выяснить — берём то, что работает везде.
    if not hardware.memory_bytes:
        return Recommendation(
            preset="light",
            reason=(
                "Характеристики машины определить не удалось, поэтому предлагаю "
                "лёгкий вариант: он работает на любом компьютере."
            ),
            findings=findings,
            limits=("Пресет можно сменить в настройках в любой момент.",),
        )

    if ram < MIN_RAM_GB:
        limits.append(
            f"Оперативной памяти {ram:.0f} ГБ — для языковой модели этого мало, "
            "перевод и режим «Инструкция» будут работать по правилам."
        )
        return Recommendation(
            preset="light",
            reason="Мало оперативной памяти, поэтому без языковой модели.",
            findings=findings,
            limits=tuple(limits),
        )

    gpu_can_run_llm = vram >= MIN_VRAM_FOR_LLM_GB
    cpu_can_run_llm = ram >= MIN_RAM_FOR_CPU_LLM_GB and cores >= MIN_CORES_FOR_CPU_LLM

    if not gpu_can_run_llm and not cpu_can_run_llm:
        if hardware.gpu_name and vram:
            limits.append(
                f"Видеопамяти {vram:.0f} ГБ — языковая модель туда не поместится "
                f"рядом с распознаванием, нужно от {MIN_VRAM_FOR_LLM_GB:.0f} ГБ."
            )
        limits.append(
            "Перевод и режим «Инструкция» останутся выключенными: на процессоре "
            "они отвечали бы слишком долго."
        )
        return Recommendation(
            preset="light",
            reason="Распознавание на процессоре, очистка по правилам — это быстро.",
            findings=findings,
            limits=tuple(limits),
        )

    if not gpu_can_run_llm:
        limits.append(
            "Языковая модель будет считаться на процессоре: ответ придёт "
            "за несколько секунд, а не мгновенно."
        )

    return Recommendation(
        preset="standard",
        reason=(
            "Машина потянет языковую модель, поэтому доступны перевод "
            "и режим «Инструкция»."
        ),
        findings=findings,
        limits=tuple(limits),
    )


def recommend_here() -> Recommendation:
    """Рекомендация для машины, на которой приложение запущено."""
    from voiceflow.platform.base import probe_hardware

    return recommend(probe_hardware())


def is_recommended(preset: str, recommendation: Recommendation) -> bool:
    """Совпадает ли выбранный пресет с предложенным."""
    return preset in PRESET_SPECS and preset == recommendation.preset
