"""Проверки на настоящих моделях.

Запускаются вручную: ``uv run pytest -m slow``. В CI пропускаются, потому что
требуют загруженных моделей и нескольких сотен мегабайт на диске.

Качество распознавания живой речи эти тесты не проверяют — для этого нужен
человек с микрофоном, см. ``docs/manual-tests.md``. Здесь фиксируется контракт:
модель находится на диске, загружается и возвращает строку на нашем формате
аудио.
"""

from __future__ import annotations

import numpy as np
import pytest

from voiceflow.core.asr.gigaam_onnx import GigaAmTranscriber
from voiceflow.core.modelstore import configure_offline_cache

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def gigaam() -> GigaAmTranscriber:
    configure_offline_cache()
    transcriber = GigaAmTranscriber(model_id="gigaam-v3-e2e-ctc", device="cpu")
    if not transcriber.is_model_ready():
        pytest.skip("Модель GigaAM не загружена, см. вкладку «Модели»")
    return transcriber


def test_model_loads_and_returns_text(gigaam: GigaAmTranscriber) -> None:
    rng = np.random.default_rng(0)
    audio = (0.01 * rng.standard_normal(16_000 * 2)).astype(np.float32)

    result = gigaam.transcribe(audio, sample_rate=16_000)

    assert isinstance(result.text, str)
    assert result.language == "ru"
    assert result.engine == "gigaam"
    assert result.audio_seconds == pytest.approx(2.0)


def test_recognition_is_faster_than_realtime(gigaam: GigaAmTranscriber) -> None:
    """Ради этого GigaAM и выбрана основной моделью для русского."""
    gigaam.load()
    audio = np.zeros(16_000 * 5, dtype=np.float32)

    result = gigaam.transcribe(audio, sample_rate=16_000)

    assert result.speed_ratio > 3.0, (
        f"Распознавание идёт медленнее ожидаемого: {result.speed_ratio:.1f}x"
    )


def test_unload_releases_the_model(gigaam: GigaAmTranscriber) -> None:
    gigaam.load()
    assert gigaam.is_loaded

    gigaam.unload()

    assert gigaam.is_loaded is False
