"""Измеритель уровня микрофона."""

from __future__ import annotations

import numpy as np
import pytest

from voiceflow.core.audio.level import LevelMeter, to_normalized_db


def test_silence_is_zero() -> None:
    assert to_normalized_db(0.0) == 0.0


def test_full_scale_is_one() -> None:
    assert to_normalized_db(1.0) == pytest.approx(1.0)


def test_below_floor_is_zero() -> None:
    # -60 дБ — это амплитуда 0.001.
    assert to_normalized_db(0.0005) == 0.0


def test_half_scale_is_in_the_middle_range() -> None:
    value = to_normalized_db(0.1)  # -20 дБ при полу -60 дБ

    assert 0.6 < value < 0.7


def test_meter_rises_quickly_and_falls_slowly() -> None:
    meter = LevelMeter(attack=0.65, release=0.12)
    loud = np.full(512, 0.5, dtype=np.float32)
    silence = np.zeros(512, dtype=np.float32)

    after_first_loud = meter.update(loud).rms
    for _ in range(5):
        meter.update(loud)
    steady = meter.current.rms

    after_first_silence = meter.update(silence).rms

    assert after_first_loud > 0.4, "нарастание должно быть быстрым"
    assert steady > after_first_loud
    # За один блок тишины уровень падает меньше, чем поднялся за один блок звука.
    assert steady - after_first_silence < after_first_loud


def test_peak_is_not_below_rms() -> None:
    meter = LevelMeter()
    block = np.zeros(512, dtype=np.float32)
    block[10] = 0.9

    for _ in range(10):
        reading = meter.update(block)

    assert reading.peak >= reading.rms


def test_values_stay_in_range_with_clipping_input() -> None:
    meter = LevelMeter()
    block = np.full(512, 5.0, dtype=np.float32)

    reading = meter.update(block)

    assert 0.0 <= reading.rms <= 1.0
    assert 0.0 <= reading.peak <= 1.0


def test_gain_increases_reading() -> None:
    quiet = np.full(512, 0.01, dtype=np.float32)

    without_gain = LevelMeter().update(quiet).rms
    with_gain = LevelMeter().update(quiet, gain=4.0).rms

    assert with_gain > without_gain


def test_reset_returns_to_silence() -> None:
    meter = LevelMeter()
    meter.update(np.full(512, 0.5, dtype=np.float32))

    meter.reset()

    assert meter.current.rms == 0.0
    assert meter.current.is_silent


def test_empty_block_keeps_previous_value() -> None:
    meter = LevelMeter()
    meter.update(np.full(512, 0.5, dtype=np.float32))
    before = meter.current.rms

    reading = meter.update(np.zeros(0, dtype=np.float32))

    assert reading.rms == before


def test_invalid_smoothing_is_rejected() -> None:
    with pytest.raises(ValueError, match="сглаживания"):
        LevelMeter(attack=0.0)
    with pytest.raises(ValueError, match="сглаживания"):
        LevelMeter(release=1.5)
