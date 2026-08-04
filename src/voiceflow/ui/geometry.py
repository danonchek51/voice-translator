"""Расчёт положения плашки на нескольких мониторах.

Функции здесь не зависят от Qt: на вход приходят простые прямоугольники,
на выход — координаты. Так поведение при отключённом мониторе и при разном
масштабе проверяется обычными тестами, без запуска интерфейса.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Отступ плашки от нижнего края экрана в положении по умолчанию.
DEFAULT_BOTTOM_MARGIN = 120


@dataclass(frozen=True, slots=True)
class ScreenRect:
    """Доступная область монитора без панели задач."""

    name: str
    x: int
    y: int
    width: int
    height: int
    is_primary: bool = False

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def contains_point(self, px: int, py: int) -> bool:
        return self.x <= px < self.right and self.y <= py < self.bottom


@dataclass(frozen=True, slots=True)
class Placement:
    """Итоговое положение плашки."""

    x: int
    y: int
    screen_name: str
    #: Положение пришлось изменить: монитор исчез или окно ушло за край.
    adjusted: bool = False


def primary_screen(screens: list[ScreenRect]) -> ScreenRect | None:
    if not screens:
        return None
    return next((screen for screen in screens if screen.is_primary), screens[0])


def find_screen(screens: list[ScreenRect], name: str) -> ScreenRect | None:
    if not name:
        return None
    return next((screen for screen in screens if screen.name == name), None)


def screen_for_point(screens: list[ScreenRect], px: int, py: int) -> ScreenRect | None:
    return next((screen for screen in screens if screen.contains_point(px, py)), None)


def clamp_to_screen(
    screen: ScreenRect, x: int, y: int, width: int, height: int
) -> tuple[int, int]:
    """Загоняет прямоугольник целиком внутрь монитора."""
    max_x = max(screen.x, screen.right - width)
    max_y = max(screen.y, screen.bottom - height)
    return (
        min(max(x, screen.x), max_x),
        min(max(y, screen.y), max_y),
    )


def default_placement(screens: list[ScreenRect], width: int, height: int) -> Placement:
    """Положение по умолчанию: снизу по центру основного монитора."""
    screen = primary_screen(screens)
    if screen is None:
        return Placement(x=0, y=0, screen_name="", adjusted=True)

    x = screen.x + (screen.width - width) // 2
    y = screen.bottom - height - DEFAULT_BOTTOM_MARGIN
    x, y = clamp_to_screen(screen, x, y, width, height)
    return Placement(x=x, y=y, screen_name=screen.name)


def resolve_placement(
    screens: list[ScreenRect],
    width: int,
    height: int,
    saved_x: int | None,
    saved_y: int | None,
    saved_screen: str = "",
) -> Placement:
    """Восстанавливает сохранённое положение с проверкой на текущие мониторы.

    Порядок проверок: сохранённый монитор на месте, иначе монитор под центром
    плашки, иначе положение по умолчанию на основном мониторе.
    """
    if not screens:
        return Placement(x=saved_x or 0, y=saved_y or 0, screen_name="", adjusted=True)
    if saved_x is None or saved_y is None:
        return default_placement(screens, width, height)

    center_x = saved_x + width // 2
    center_y = saved_y + height // 2

    target = find_screen(screens, saved_screen)
    if target is not None:
        x, y = clamp_to_screen(target, saved_x, saved_y, width, height)
        return Placement(
            x=x,
            y=y,
            screen_name=target.name,
            adjusted=(x, y) != (saved_x, saved_y),
        )

    # Монитор с сохранённым именем исчез: ищем тот, где сейчас центр плашки.
    under_center = screen_for_point(screens, center_x, center_y)
    if under_center is not None:
        x, y = clamp_to_screen(under_center, saved_x, saved_y, width, height)
        return Placement(
            x=x,
            y=y,
            screen_name=under_center.name,
            adjusted=True,
        )

    fallback = default_placement(screens, width, height)
    return Placement(
        x=fallback.x,
        y=fallback.y,
        screen_name=fallback.screen_name,
        adjusted=True,
    )
