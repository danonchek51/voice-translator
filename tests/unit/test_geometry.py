"""Положение плашки на нескольких мониторах."""

from __future__ import annotations

from voiceflow.ui.geometry import (
    ScreenRect,
    clamp_to_screen,
    default_placement,
    find_screen,
    primary_screen,
    resolve_placement,
    screen_for_point,
)

MAIN = ScreenRect(name="DISPLAY1", x=0, y=0, width=1920, height=1040, is_primary=True)
SECOND = ScreenRect(name="DISPLAY2", x=1920, y=-200, width=2560, height=1440)
LEFT = ScreenRect(name="DISPLAY3", x=-1280, y=0, width=1280, height=1024)

WIDTH, HEIGHT = 190, 44


def test_primary_screen_is_found() -> None:
    assert primary_screen([SECOND, MAIN]) is MAIN
    # Без явного основного берём первый.
    assert primary_screen([SECOND]) is SECOND
    assert primary_screen([]) is None


def test_find_screen_by_name() -> None:
    assert find_screen([MAIN, SECOND], "DISPLAY2") is SECOND
    assert find_screen([MAIN, SECOND], "НЕТ") is None
    assert find_screen([MAIN], "") is None


def test_screen_for_point() -> None:
    assert screen_for_point([MAIN, SECOND], 100, 100) is MAIN
    assert screen_for_point([MAIN, SECOND], 2000, 100) is SECOND
    assert screen_for_point([MAIN, SECOND], -50, 100) is None


def test_clamp_keeps_window_inside() -> None:
    assert clamp_to_screen(MAIN, -100, -100, WIDTH, HEIGHT) == (0, 0)
    assert clamp_to_screen(MAIN, 5000, 5000, WIDTH, HEIGHT) == (1920 - WIDTH, 1040 - HEIGHT)
    assert clamp_to_screen(MAIN, 300, 400, WIDTH, HEIGHT) == (300, 400)


def test_clamp_handles_window_larger_than_screen() -> None:
    tiny = ScreenRect(name="T", x=0, y=0, width=100, height=30)

    assert clamp_to_screen(tiny, 50, 50, WIDTH, HEIGHT) == (0, 0)


def test_default_placement_is_bottom_center_of_primary() -> None:
    placement = default_placement([MAIN, SECOND], WIDTH, HEIGHT)

    assert placement.screen_name == "DISPLAY1"
    assert placement.x == (1920 - WIDTH) // 2
    assert placement.y == 1040 - HEIGHT - 120
    assert placement.adjusted is False


def test_default_placement_without_screens() -> None:
    placement = default_placement([], WIDTH, HEIGHT)

    assert placement.adjusted is True
    assert placement.screen_name == ""


def test_first_run_uses_default_position() -> None:
    placement = resolve_placement([MAIN], WIDTH, HEIGHT, saved_x=None, saved_y=None)

    assert (placement.x, placement.y) == (
        default_placement([MAIN], WIDTH, HEIGHT).x,
        default_placement([MAIN], WIDTH, HEIGHT).y,
    )


def test_saved_position_is_restored_as_is() -> None:
    placement = resolve_placement(
        [MAIN, SECOND], WIDTH, HEIGHT, saved_x=2200, saved_y=300, saved_screen="DISPLAY2"
    )

    assert (placement.x, placement.y) == (2200, 300)
    assert placement.screen_name == "DISPLAY2"
    assert placement.adjusted is False


def test_position_outside_its_screen_is_clamped() -> None:
    placement = resolve_placement(
        [MAIN], WIDTH, HEIGHT, saved_x=1900, saved_y=1030, saved_screen="DISPLAY1"
    )

    assert placement.x == 1920 - WIDTH
    assert placement.y == 1040 - HEIGHT
    assert placement.adjusted is True


def test_disconnected_monitor_falls_back_to_default() -> None:
    """Плашка стояла на втором мониторе, монитор отключили."""
    placement = resolve_placement(
        [MAIN], WIDTH, HEIGHT, saved_x=2200, saved_y=300, saved_screen="DISPLAY2"
    )

    assert placement.screen_name == "DISPLAY1"
    assert placement.adjusted is True
    assert MAIN.contains_point(placement.x, placement.y)


def test_renamed_monitor_is_found_by_position() -> None:
    """Имя монитора изменилось, но плашка физически осталась на нём."""
    placement = resolve_placement(
        [MAIN, SECOND], WIDTH, HEIGHT, saved_x=2200, saved_y=300, saved_screen="СТАРОЕ_ИМЯ"
    )

    assert placement.screen_name == "DISPLAY2"
    assert (placement.x, placement.y) == (2200, 300)
    assert placement.adjusted is True


def test_negative_coordinates_on_left_monitor_work() -> None:
    placement = resolve_placement(
        [MAIN, LEFT], WIDTH, HEIGHT, saved_x=-800, saved_y=500, saved_screen="DISPLAY3"
    )

    assert (placement.x, placement.y) == (-800, 500)
    assert placement.screen_name == "DISPLAY3"


def test_no_screens_keeps_saved_values() -> None:
    placement = resolve_placement([], WIDTH, HEIGHT, saved_x=10, saved_y=20)

    assert (placement.x, placement.y) == (10, 20)
    assert placement.adjusted is True
