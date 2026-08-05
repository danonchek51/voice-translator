"""Оформление: тема, цвета, вид индикатора.

Цвет нельзя подобрать вслепую по названию — его нужно видеть, поэтому
изменения применяются сразу. Настройки при этом остаются прежними, пока
человек не нажмёт «Сохранить».
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from voiceflow.core.settings.schema import AppearanceSettings, Settings, validate
from voiceflow.ui import style, theme


@pytest.fixture(scope="module")
def qt_app() -> Iterator[object]:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def restore_theme() -> Iterator[None]:
    yield
    theme.apply(AppearanceSettings())


# --------------------------------------------------------------------------- #
# Палитры
# --------------------------------------------------------------------------- #


def test_light_theme_is_actually_light() -> None:
    dark = style.palette_for("dark")
    light = style.palette_for("light")

    assert light.base != dark.base
    assert light.text != dark.text
    # Фон светлее текста — иначе это не светлая тема.
    assert light.base > light.text


def test_accent_replaces_only_the_accent() -> None:
    palette = style.palette_for("dark", "#ff0000")

    assert palette.accent == "#ff0000"
    assert palette.base == style.PALETTE.base


def test_hover_colour_is_derived_from_accent() -> None:
    palette = style.palette_for("dark", "#2f6fed")

    assert palette.accent_hover != palette.accent
    assert palette.accent_hover.startswith("#")


def test_unknown_theme_falls_back() -> None:
    assert style.palette_for("что-то своё").base == style.PALETTE.base


def test_ready_made_accents_are_valid_colours() -> None:
    for title, colour in style.ACCENT_PRESETS.items():
        assert colour.startswith("#") and len(colour) == 7, title
        int(colour[1:], 16)


# --------------------------------------------------------------------------- #
# Применение
# --------------------------------------------------------------------------- #


def test_applying_theme_changes_overlay_colours() -> None:
    before = theme.BACKGROUND

    theme.apply(AppearanceSettings(theme="light"))

    assert theme.BACKGROUND != before
    assert theme.TEXT == style.LIGHT.text


def test_overlay_colour_overrides_the_theme() -> None:
    theme.apply(AppearanceSettings(overlay_color="#123456"))

    assert theme.BACKGROUND == "#123456"


def test_wave_colour_is_separate_from_accent() -> None:
    theme.apply(AppearanceSettings(accent="#ff0000", wave_color="#00ff00"))

    assert theme.METER_FILL == "#00ff00"


def test_wave_follows_accent_when_not_set() -> None:
    theme.apply(AppearanceSettings(accent="#ff0000"))

    assert theme.METER_FILL == "#ff0000"


def test_state_colours_follow_the_palette() -> None:
    from voiceflow.core.state import AppState

    theme.apply(AppearanceSettings(theme="light"))

    assert theme.style_for(AppState.LISTENING).color == style.LIGHT.accent


# --------------------------------------------------------------------------- #
# Проверка значений
# --------------------------------------------------------------------------- #


def test_broken_colour_is_replaced_not_crashed() -> None:
    settings = Settings()
    settings.appearance.accent = "красный"

    notes = validate(settings)

    assert settings.appearance.accent == ""
    assert any("не похоже на цвет" in note for note in notes)


def test_unknown_indicator_is_replaced() -> None:
    settings = Settings()
    settings.appearance.indicator = "спираль"

    validate(settings)

    assert settings.appearance.indicator == "wave"


def test_valid_colour_survives() -> None:
    settings = Settings()
    settings.appearance.accent = "#A1B2C3"

    validate(settings)

    assert settings.appearance.accent == "#A1B2C3"


# --------------------------------------------------------------------------- #
# Вид индикатора
# --------------------------------------------------------------------------- #


def test_every_indicator_draws_without_error(qt_app) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtGui import QPixmap

    from voiceflow.ui.widgets.wave_meter import STYLES, WaveMeter

    for name in STYLES:
        meter = WaveMeter()
        meter.resize(180, 18)
        meter.set_style(name)
        meter.set_level(0.6, 0.8)
        for _ in range(5):
            meter._advance()
        meter.render(QPixmap(meter.size()))


def test_unknown_indicator_falls_back_to_wave(qt_app) -> None:  # type: ignore[no-untyped-def]
    from voiceflow.ui.widgets.wave_meter import WaveMeter

    meter = WaveMeter()
    meter.set_style("спираль")

    assert meter._style == "wave"


def test_indicator_choices_match_the_schema() -> None:
    from voiceflow.core.settings.schema import INDICATORS
    from voiceflow.ui.widgets.wave_meter import STYLES

    assert set(INDICATORS) == set(STYLES)


def test_appearance_tab_lists_every_indicator(qt_app) -> None:  # type: ignore[no-untyped-def]
    from voiceflow.core.settings.schema import INDICATORS
    from voiceflow.ui.settings_window.tab_appearance import AppearanceTab

    tab = AppearanceTab()
    listed = {tab.indicator.itemData(i) for i in range(tab.indicator.count())}

    assert listed == set(INDICATORS)


def test_appearance_tab_round_trips_settings(qt_app) -> None:  # type: ignore[no-untyped-def]
    from voiceflow.ui.settings_window.tab_appearance import AppearanceTab

    settings = Settings()
    settings.appearance.theme = "light"
    settings.appearance.accent = "#112233"
    settings.appearance.indicator = "pulse"
    settings.overlay.opacity = 70

    tab = AppearanceTab()
    tab.load_from(settings)

    written = Settings()
    tab.apply_to(written)

    assert written.appearance.theme == "light"
    assert written.appearance.accent == "#112233"
    assert written.appearance.indicator == "pulse"
    assert written.overlay.opacity == 70


def test_changing_a_colour_asks_for_preview(qt_app) -> None:  # type: ignore[no-untyped-def]
    from voiceflow.ui.settings_window.tab_appearance import AppearanceTab

    tab = AppearanceTab()
    asked: list[int] = []
    tab.preview_requested.connect(lambda: asked.append(1))

    tab.accent.set_value("#ff0000")
    tab.accent.changed.emit("#ff0000")

    assert asked, "цвет нужно видеть сразу, иначе его не подобрать"
