"""Волна уровня микрофона.

Главное требование — плавность: уровень приходит неровно, и волна не должна
прыгать к новому значению за один кадр.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from itertools import pairwise

import pytest


@pytest.fixture(scope="module")
def qt_app() -> Iterator[object]:
    """Qt без окон: тест должен проходить на машине без графической сессии."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


@pytest.fixture
def wave(qt_app):  # type: ignore[no-untyped-def]
    from voiceflow.ui.widgets.wave_meter import WaveMeter

    return WaveMeter()


def _frames(wave, count: int) -> None:  # type: ignore[no-untyped-def]
    for _ in range(count):
        wave._advance()


def test_starts_at_rest(wave) -> None:  # type: ignore[no-untyped-def]
    assert set(wave.amplitudes) == {0.0}


def test_level_does_not_jump_in_one_frame(wave) -> None:  # type: ignore[no-untyped-def]
    """Мгновенная подстановка значения и давала дёрганую анимацию."""
    wave.set_level(1.0, 1.0)
    _frames(wave, 1)

    newest = wave.amplitudes[-1]

    assert 0.0 < newest < 1.0


def test_level_approaches_target_over_frames(wave) -> None:  # type: ignore[no-untyped-def]
    from voiceflow.ui.widgets.wave_meter import WaveMeter

    grown: list[float] = []
    for _ in range(6):
        wave.set_level(0.8, 0.8)
        wave._advance()
        grown.append(wave.amplitudes[-1])

    assert grown == sorted(grown), "волна должна нарастать монотонно"
    assert grown[-1] > grown[0]
    assert isinstance(wave, WaveMeter)


def test_neighbouring_points_stay_close(wave) -> None:  # type: ignore[no-untyped-def]
    """Соседние точки волны не должны отличаться скачком."""
    for step in range(20):
        wave.set_level(1.0 if step % 2 else 0.0, 0.0)
        wave._advance()

    values = wave.amplitudes
    jumps = [abs(b - a) for a, b in pairwise(values)]

    assert max(jumps) < 0.4


def test_calms_down_when_data_stops(wave) -> None:  # type: ignore[no-untyped-def]
    wave.set_level(0.9, 0.9)
    _frames(wave, 5)
    assert max(wave.amplitudes) > 0.0

    _frames(wave, 200)

    assert max(wave.amplitudes) == pytest.approx(0.0, abs=0.01)


def test_stops_animating_at_rest(wave) -> None:  # type: ignore[no-untyped-def]
    wave.set_level(0.5, 0.5)
    assert wave._timer.isActive()

    _frames(wave, 250)

    assert not wave._timer.isActive(), "в покое таймер не должен жечь процессор"


def test_reset_clears_immediately(wave) -> None:  # type: ignore[no-untyped-def]
    wave.set_level(0.9, 0.9)
    _frames(wave, 10)

    wave.reset()

    assert set(wave.amplitudes) == {0.0}
    assert not wave._timer.isActive()


def test_values_out_of_range_are_clamped(wave) -> None:  # type: ignore[no-untyped-def]
    wave.set_level(5.0, 5.0)
    _frames(wave, 60)

    assert max(wave.amplitudes) <= 1.0

    wave.set_level(-2.0, -2.0)
    _frames(wave, 5)

    assert min(wave.amplitudes) >= 0.0


def test_peak_lifts_a_quiet_signal(wave) -> None:  # type: ignore[no-untyped-def]
    from voiceflow.ui.widgets.wave_meter import WaveMeter

    quiet = WaveMeter()
    quiet.set_level(0.1, 0.1)
    _frames(quiet, 4)

    spiky = WaveMeter()
    spiky.set_level(0.1, 0.9)
    _frames(spiky, 4)

    assert spiky.amplitudes[-1] > quiet.amplitudes[-1]


def test_quiet_signal_is_visible(wave) -> None:  # type: ignore[no-untyped-def]
    """На тихом микрофоне линейная шкала оставляла волну почти плоской."""
    from voiceflow.ui.widgets.wave_meter import _shape

    assert _shape(0.2) > 0.2
    assert _shape(1.0) == pytest.approx(1.0)
    assert _shape(0.0) == 0.0

    wave.set_level(0.2, 0.2)
    _frames(wave, 8)

    assert max(wave.amplitudes) > 0.2


def test_display_curve_keeps_order(wave) -> None:  # type: ignore[no-untyped-def]
    """Кривая поднимает тихое, но громкое всё равно должно быть выше."""
    from voiceflow.ui.widgets.wave_meter import _shape

    values = [_shape(v) for v in (0.05, 0.2, 0.5, 0.9)]

    assert values == sorted(values)
    assert all(v <= 1.0 for v in values)


def test_taper_softens_the_edges() -> None:
    from voiceflow.ui.widgets.wave_meter import POINTS, _taper

    assert _taper(0, POINTS) < _taper(POINTS // 2, POINTS)
    assert _taper(POINTS - 1, POINTS) < _taper(POINTS // 2, POINTS)
    assert _taper(POINTS // 2, POINTS) == pytest.approx(1.0)


def test_paint_survives_every_state(wave) -> None:  # type: ignore[no-untyped-def]
    """Отрисовка не должна падать ни в покое, ни на всплеске."""
    from PySide6.QtGui import QPixmap

    wave.resize(196, 18)
    for levels in ((0.0, 0.0), (0.5, 0.7), (1.0, 1.0)):
        wave.set_level(*levels)
        _frames(wave, 3)
        wave.render(QPixmap(wave.size()))
