"""Подбор конфигурации под машину.

Человек не обязан знать, потянет ли его компьютер модель на четыре
миллиарда параметров. Правило осторожное: предлагаем то, что точно будет
работать быстро.
"""

from __future__ import annotations

import pytest

from voiceflow.core.models.advisor import (
    MIN_VRAM_FOR_LLM_GB,
    describe_machine,
    is_recommended,
    recommend,
)
from voiceflow.platform.base import HardwareInfo


def machine(cores: int = 8, ram_gb: float = 16, gpu: str = "", vram_gb: float = 0) -> HardwareInfo:
    return HardwareInfo(
        cores=cores,
        memory_bytes=int(ram_gb * 1024**3),
        gpu_name=gpu,
        gpu_memory_bytes=int(vram_gb * 1024**3),
    )


# --------------------------------------------------------------------------- #
# Выбор пресета
# --------------------------------------------------------------------------- #


def test_gaming_machine_gets_language_model() -> None:
    result = recommend(machine(cores=12, ram_gb=32, gpu="NVIDIA GeForce RTX 4070", vram_gb=12))

    assert result.preset == "standard"
    assert "языковую модель" in result.reason


def test_office_laptop_gets_light_preset() -> None:
    """Четыре ядра и восемь гигабайт без видеокарты — только очистка правилами."""
    result = recommend(machine(cores=4, ram_gb=8))

    assert result.preset == "light"
    assert any("Инструкция" in note for note in result.limits)


def test_weak_machine_is_told_why() -> None:
    result = recommend(machine(cores=2, ram_gb=4))

    assert result.preset == "light"
    assert result.limits, "человеку нужно объяснить, чего не хватает"
    assert any("памяти" in note for note in result.limits)


def test_small_video_memory_is_explained() -> None:
    """Шести гигабайт видеопамяти под модель и распознавание сразу не хватит."""
    result = recommend(machine(cores=4, ram_gb=8, gpu="NVIDIA GeForce GTX 1050", vram_gb=2))

    assert result.preset == "light"
    assert any(str(int(MIN_VRAM_FOR_LLM_GB)) in note for note in result.limits)


def test_strong_processor_without_gpu_still_gets_llm() -> None:
    """Много ядер и памяти: модель посчитается на процессоре, но медленнее."""
    result = recommend(machine(cores=16, ram_gb=32))

    assert result.preset == "standard"
    assert any("на процессоре" in note for note in result.limits)


def test_unknown_machine_falls_back_to_safe_choice() -> None:
    result = recommend(HardwareInfo())

    assert result.preset == "light"
    assert "определить не удалось" in result.reason


# --------------------------------------------------------------------------- #
# Что показывается человеку
# --------------------------------------------------------------------------- #


def test_findings_are_readable() -> None:
    text = " ".join(
        describe_machine(machine(cores=12, ram_gb=32, gpu="NVIDIA RTX 2060", vram_gb=6))
    )

    assert "12 логических ядер" in text
    assert "32 ГБ оперативной памяти" in text
    assert "NVIDIA RTX 2060" in text
    assert "6 ГБ видеопамяти" in text


def test_missing_gpu_is_stated_plainly() -> None:
    text = " ".join(describe_machine(machine(gpu="")))

    assert "видеокарта не найдена" in text


def test_recommendation_has_a_title() -> None:
    result = recommend(machine(cores=12, ram_gb=32, gpu="NVIDIA RTX 4070", vram_gb=12))

    assert result.title == "Стандарт"


def test_matching_preset_is_recognised() -> None:
    result = recommend(machine(cores=4, ram_gb=8))

    assert is_recommended("light", result) is True
    assert is_recommended("quality", result) is False


def test_every_recommendation_points_at_a_real_preset() -> None:
    from voiceflow.core.models.presets import PRESET_SPECS

    machines = [
        HardwareInfo(),
        machine(cores=2, ram_gb=4),
        machine(cores=4, ram_gb=8),
        machine(cores=8, ram_gb=16),
        machine(cores=16, ram_gb=64, gpu="NVIDIA RTX 4090", vram_gb=24),
    ]
    for info in machines:
        assert recommend(info).preset in PRESET_SPECS


# --------------------------------------------------------------------------- #
# Опрос реальной машины
# --------------------------------------------------------------------------- #


def test_probe_returns_something_usable() -> None:
    """Опрос не должен падать ни на какой машине."""
    from voiceflow.platform.base import probe_hardware

    info = probe_hardware()

    assert info.cores >= 0
    assert info.memory_bytes >= 0
    assert isinstance(info.gpu_name, str)


@pytest.mark.parametrize("ram_gb", [4, 8, 16, 32, 64])
def test_recommendation_never_throws(ram_gb: int) -> None:
    assert recommend(machine(ram_gb=ram_gb)).reason
