"""Кольцевой буфер аудио.

Нужен для pre-roll: между началом фразы и срабатыванием детектора проходит
несколько сотен миллисекунд, и без буфера начало речи теряется.

Буфер живёт только в памяти и перезаписывается по кругу — на диск ничего
не попадает.
"""

from __future__ import annotations

import threading

import numpy as np


class RingBuffer:
    """Потокобезопасный кольцевой буфер одноканального ``float32``."""

    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("Ёмкость буфера должна быть положительной")
        self._capacity = capacity
        self._data = np.zeros(capacity, dtype=np.float32)
        self._write_pos = 0
        self._filled = 0
        self._lock = threading.Lock()

    @classmethod
    def for_seconds(cls, seconds: float, sample_rate: int) -> RingBuffer:
        return cls(max(1, round(seconds * sample_rate)))

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def filled(self) -> int:
        """Сколько отсчётов реально накоплено."""
        with self._lock:
            return self._filled

    def write(self, block: np.ndarray) -> None:
        """Дописывает блок. Блок длиннее ёмкости обрезается с начала."""
        data = np.asarray(block, dtype=np.float32).reshape(-1)
        if data.size == 0:
            return

        with self._lock:
            if data.size >= self._capacity:
                self._data[:] = data[-self._capacity :]
                self._write_pos = 0
                self._filled = self._capacity
                return

            end = self._write_pos + data.size
            if end <= self._capacity:
                self._data[self._write_pos : end] = data
            else:
                head = self._capacity - self._write_pos
                self._data[self._write_pos :] = data[:head]
                self._data[: data.size - head] = data[head:]

            self._write_pos = end % self._capacity
            self._filled = min(self._capacity, self._filled + data.size)

    def read_all(self) -> np.ndarray:
        """Всё накопленное в хронологическом порядке. Возвращает копию."""
        with self._lock:
            return self._read_last_locked(self._filled)

    def read_last(self, count: int) -> np.ndarray:
        """Последние ``count`` отсчётов. Если их меньше — сколько есть."""
        if count <= 0:
            return np.zeros(0, dtype=np.float32)
        with self._lock:
            return self._read_last_locked(min(count, self._filled))

    def _read_last_locked(self, count: int) -> np.ndarray:
        if count == 0:
            return np.zeros(0, dtype=np.float32)
        start = (self._write_pos - count) % self._capacity
        end = start + count
        if end <= self._capacity:
            return self._data[start:end].copy()
        head = self._capacity - start
        return np.concatenate((self._data[start:], self._data[: count - head]))

    def clear(self) -> None:
        with self._lock:
            self._data.fill(0.0)
            self._write_pos = 0
            self._filled = 0
