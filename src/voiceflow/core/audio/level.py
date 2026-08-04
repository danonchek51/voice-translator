"""Измеритель уровня микрофона.

Считается прямо из блока аудио, наружу уходит одно число в диапазоне 0..1.
Само аудио не покидает память приложения.

Сглаживание асимметричное: быстрое нарастание, чтобы полоска реагировала
мгновенно, и медленный спад, чтобы она не дёргалась между слогами.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

#: Ниже этого уровня считаем, что тишина. Полоска в нуле.
DEFAULT_FLOOR_DB = -60.0


@dataclass(frozen=True, slots=True)
class LevelReading:
    """Сглаженные значения в диапазоне 0..1."""

    rms: float
    peak: float

    @property
    def is_silent(self) -> bool:
        return self.peak <= 0.001


SILENT = LevelReading(rms=0.0, peak=0.0)


def to_normalized_db(amplitude: float, floor_db: float = DEFAULT_FLOOR_DB) -> float:
    """Переводит амплитуду 0..1 в нормированные децибелы 0..1."""
    if amplitude <= 0.0:
        return 0.0
    db = 20.0 * math.log10(min(amplitude, 1.0))
    if db <= floor_db:
        return 0.0
    return min(1.0, (db - floor_db) / -floor_db)


class LevelMeter:
    """Держит текущее сглаженное значение уровня."""

    def __init__(
        self,
        floor_db: float = DEFAULT_FLOOR_DB,
        attack: float = 0.65,
        release: float = 0.12,
    ) -> None:
        if not 0.0 < attack <= 1.0 or not 0.0 < release <= 1.0:
            raise ValueError("Коэффициенты сглаживания должны быть в диапазоне (0, 1]")
        self._floor_db = floor_db
        self._attack = attack
        self._release = release
        self._rms = 0.0
        self._peak = 0.0

    @property
    def current(self) -> LevelReading:
        return LevelReading(rms=self._rms, peak=self._peak)

    def reset(self) -> None:
        self._rms = 0.0
        self._peak = 0.0

    def update(self, block: np.ndarray, gain: float = 1.0) -> LevelReading:
        """Обновляет уровень по очередному блоку."""
        data = np.asarray(block, dtype=np.float32).reshape(-1)
        if data.size == 0:
            return self.current

        if gain != 1.0:
            data = data * gain

        raw_rms = float(np.sqrt(np.mean(np.square(data, dtype=np.float64))))
        raw_peak = float(np.max(np.abs(data)))

        self._rms = self._smooth(self._rms, to_normalized_db(raw_rms, self._floor_db))
        self._peak = self._smooth(self._peak, to_normalized_db(raw_peak, self._floor_db))
        return self.current

    def _smooth(self, current: float, target: float) -> float:
        coefficient = self._attack if target > current else self._release
        return current + coefficient * (target - current)
