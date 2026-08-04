"""Кольцевой буфер pre-roll."""

from __future__ import annotations

import threading

import numpy as np
import pytest

from voiceflow.core.audio.ring_buffer import RingBuffer


def test_capacity_must_be_positive() -> None:
    with pytest.raises(ValueError, match="положительной"):
        RingBuffer(0)


def test_for_seconds_converts_to_samples() -> None:
    assert RingBuffer.for_seconds(2.0, 16_000).capacity == 32_000
    # Слишком короткий интервал всё равно даёт рабочий буфер.
    assert RingBuffer.for_seconds(0.0, 16_000).capacity == 1


def test_empty_buffer_reads_nothing() -> None:
    buffer = RingBuffer(10)

    assert buffer.filled == 0
    assert buffer.read_all().size == 0
    assert buffer.read_last(5).size == 0


def test_partial_fill_returns_written_data() -> None:
    buffer = RingBuffer(10)
    buffer.write(np.array([1, 2, 3], dtype=np.float32))

    assert buffer.filled == 3
    np.testing.assert_array_equal(buffer.read_all(), [1, 2, 3])


def test_wraps_and_keeps_chronological_order() -> None:
    buffer = RingBuffer(5)
    buffer.write(np.arange(1, 5, dtype=np.float32))
    buffer.write(np.arange(5, 9, dtype=np.float32))

    assert buffer.filled == 5
    np.testing.assert_array_equal(buffer.read_all(), [4, 5, 6, 7, 8])


def test_block_larger_than_capacity_keeps_tail() -> None:
    buffer = RingBuffer(4)
    buffer.write(np.arange(1, 11, dtype=np.float32))

    np.testing.assert_array_equal(buffer.read_all(), [7, 8, 9, 10])


def test_read_last_limits_to_available() -> None:
    buffer = RingBuffer(10)
    buffer.write(np.arange(1, 6, dtype=np.float32))

    np.testing.assert_array_equal(buffer.read_last(3), [3, 4, 5])
    np.testing.assert_array_equal(buffer.read_last(99), [1, 2, 3, 4, 5])
    assert buffer.read_last(0).size == 0


def test_read_returns_a_copy() -> None:
    buffer = RingBuffer(4)
    buffer.write(np.array([1, 2, 3, 4], dtype=np.float32))

    snapshot = buffer.read_all()
    snapshot[0] = 99.0

    np.testing.assert_array_equal(buffer.read_all(), [1, 2, 3, 4])


def test_clear_empties_buffer() -> None:
    buffer = RingBuffer(4)
    buffer.write(np.array([1, 2, 3], dtype=np.float32))

    buffer.clear()

    assert buffer.filled == 0
    assert buffer.read_all().size == 0


def test_empty_write_is_ignored() -> None:
    buffer = RingBuffer(4)
    buffer.write(np.zeros(0, dtype=np.float32))

    assert buffer.filled == 0


def test_accepts_two_dimensional_block() -> None:
    """PortAudio отдаёт блок формой (frames, channels)."""
    buffer = RingBuffer(4)
    buffer.write(np.array([[1.0], [2.0], [3.0]], dtype=np.float32))

    np.testing.assert_array_equal(buffer.read_all(), [1, 2, 3])


def test_concurrent_writes_do_not_corrupt_state() -> None:
    buffer = RingBuffer(1024)
    block = np.ones(64, dtype=np.float32)

    def writer() -> None:
        for _ in range(200):
            buffer.write(block)

    threads = [threading.Thread(target=writer) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert buffer.filled == 1024
    np.testing.assert_array_equal(buffer.read_all(), np.ones(1024, dtype=np.float32))
