"""Подсказки при наведении.

Настройка без объяснения бесполезна: человек не знает, что изменится, и
не трогает её. Тесты следят, что подсказка есть у каждого поля и что она
объясняет последствие, а не пересказывает название.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from voiceflow.ui.hints import ALL_HINTS, MODELS, PRESET_TOOLTIPS, model_hint


@pytest.fixture(scope="module")
def qt_app() -> Iterator[object]:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


# --------------------------------------------------------------------------- #
# Качество текста
# --------------------------------------------------------------------------- #


def test_every_hint_is_a_sentence() -> None:
    for group, hints in ALL_HINTS.items():
        for key, text in hints.items():
            assert len(text) > 30, f"{group}.{key}: слишком коротко, чтобы объяснить"
            first = text.lstrip("«\"'")[0]
            assert first.isupper(), f"{group}.{key}: начинается со строчной"
            assert text.rstrip().endswith("."), f"{group}.{key}: нет точки в конце"


def test_hints_do_not_just_repeat_the_name() -> None:
    """«Включает автозапуск» ничего не объясняет."""
    for group, hints in ALL_HINTS.items():
        for key, text in hints.items():
            assert not text.lower().startswith("включает"), f"{group}.{key}"
            assert not text.lower().startswith("опция"), f"{group}.{key}"


# --------------------------------------------------------------------------- #
# Полнота
# --------------------------------------------------------------------------- #


def test_every_model_in_the_registry_is_explained() -> None:
    """Человек должен понимать, за что платит гигабайтами."""
    from voiceflow.core.models.catalog import load_catalog

    for spec in load_catalog().models:
        assert spec.id in MODELS, f"нет описания модели «{spec.id}»"


def test_every_preset_is_explained() -> None:
    from voiceflow.core.models.presets import PRESET_SPECS

    for preset in PRESET_SPECS:
        assert preset in PRESET_TOOLTIPS, f"нет описания пресета «{preset}»"


def test_model_hint_falls_back() -> None:
    assert model_hint("gigaam-v3-e2e-rnnt")
    assert model_hint("нет-такой", "запасной текст") == "запасной текст"


# --------------------------------------------------------------------------- #
# Подключение к вкладкам
# --------------------------------------------------------------------------- #


def test_hints_reach_their_fields(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Опечатка в имени поля оставила бы настройку без подсказки молча."""
    from voiceflow.ui.settings_window.tab_activation import ActivationTab
    from voiceflow.ui.settings_window.tab_processing import ProcessingTab

    for factory in (ActivationTab, ProcessingTab):
        tab = factory()
        missing = tab.apply_hints()
        assert missing == [], f"{factory.__name__}: подсказки без полей: {missing}"


def test_applied_hint_is_visible_on_the_widget(qt_app) -> None:  # type: ignore[no-untyped-def]
    from voiceflow.ui.hints import ACTIVATION
    from voiceflow.ui.settings_window.tab_activation import ActivationTab

    tab = ActivationTab()
    tab.apply_hints()

    assert tab.wake_phrase.toolTip() == ACTIVATION["wake_phrase"]
    assert tab.hotkey.toolTip() == ACTIVATION["hotkey"]


def test_processing_steps_explain_themselves(qt_app) -> None:  # type: ignore[no-untyped-def]
    from voiceflow.ui.settings_window.tab_processing import ProcessingTab

    tab = ProcessingTab()

    for step_id, box in tab.step_boxes.items():
        assert box.toolTip(), f"шаг «{step_id}» без объяснения"
