"""Эталонные примеры очистки.

Проверяют поведение целиком, на реальных фразах, а не по отдельным правилам.
Именно здесь ловятся регрессии после правки словаря или порядка шагов.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest

from voiceflow.core.text.rules import clean, load_fillers

GOLDEN_FILE = Path(__file__).resolve().parents[1] / "fixtures" / "golden_cleanup.toml"


def load_cases() -> list[dict[str, Any]]:
    with GOLDEN_FILE.open("rb") as handle:
        data = tomllib.load(handle)
    cases = data.get("case", [])
    assert cases, "файл эталонов пуст"
    return list(cases)


CASES = load_cases()


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_golden_cleanup(case: dict[str, Any]) -> None:
    result = clean(case["raw"], load_fillers())

    assert result.text == case["expected"]


def test_cleanup_is_idempotent() -> None:
    """Повторная очистка уже очищенного текста ничего не меняет."""
    fillers = load_fillers()
    for case in CASES:
        once = clean(case["raw"], fillers).text
        twice = clean(once, fillers).text
        assert twice == once, f"неустойчивый случай: {case['name']}"
