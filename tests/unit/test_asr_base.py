"""Базовое поведение движков распознавания."""

from __future__ import annotations

import numpy as np
import pytest

from tests.fakes import FakeTranscriber
from voiceflow.core.asr.base import (
    MIN_AUDIO_SECONDS,
    BackendUnavailableError,
    TranscriberError,
    TranscriptResult,
)


def audio(seconds: float, sample_rate: int = 16_000) -> np.ndarray:
    return np.ones(int(seconds * sample_rate), dtype=np.float32)


def test_transcribe_returns_text() -> None:
    transcriber = FakeTranscriber(text="привет мир")

    result = transcriber.transcribe(audio(1.0), sample_rate=16_000)

    assert result.text == "привет мир"
    assert result.language == "ru"
    assert result.engine == "fake"
    assert result.model_id == "fake-model"
    assert result.audio_seconds == pytest.approx(1.0)
    assert result.is_empty is False
    assert result.empty_reason == ""


def test_short_audio_skips_the_model() -> None:
    """Случайный щелчок не должен будить модель."""
    transcriber = FakeTranscriber()

    result = transcriber.transcribe(audio(MIN_AUDIO_SECONDS / 2), sample_rate=16_000)

    assert result.is_empty
    assert result.empty_reason == "запись слишком короткая"
    assert transcriber.calls == []
    assert transcriber.load_count == 0


def test_empty_result_is_explained() -> None:
    transcriber = FakeTranscriber(text="   ")

    result = transcriber.transcribe(audio(1.0), sample_rate=16_000)

    assert result.is_empty
    assert result.empty_reason == "речь не распознана"


def test_model_is_loaded_once() -> None:
    transcriber = FakeTranscriber()

    transcriber.transcribe(audio(1.0), sample_rate=16_000)
    transcriber.transcribe(audio(1.0), sample_rate=16_000)

    assert transcriber.load_count == 1
    assert transcriber.is_loaded is True


def test_unload_frees_the_model() -> None:
    transcriber = FakeTranscriber()
    transcriber.load()

    transcriber.unload()

    assert transcriber.is_loaded is False
    transcriber.load()
    assert transcriber.load_count == 2


def test_unload_without_load_is_safe() -> None:
    FakeTranscriber().unload()


def test_missing_backend_is_reported_clearly() -> None:
    transcriber = FakeTranscriber(backend_available=False)

    with pytest.raises(BackendUnavailableError, match="Не установлена библиотека"):
        transcriber.load()


def test_language_is_passed_to_the_engine() -> None:
    transcriber = FakeTranscriber()

    transcriber.transcribe(audio(1.0), sample_rate=16_000, language="en")

    assert transcriber.calls[-1][1] == "en"


def test_engine_error_propagates() -> None:
    transcriber = FakeTranscriber(raises=TranscriberError("модель упала"))

    with pytest.raises(TranscriberError, match="модель упала"):
        transcriber.transcribe(audio(1.0), sample_rate=16_000)


def test_speed_ratio_is_computed() -> None:
    result = TranscriptResult(
        text="текст",
        language="ru",
        engine="fake",
        model_id="fake-model",
        audio_seconds=60.0,
        elapsed_seconds=3.0,
    )

    assert result.speed_ratio == pytest.approx(20.0)


def test_speed_ratio_survives_instant_result() -> None:
    """Часы могут показать нулевую длительность — делить на ноль нельзя."""
    result = TranscriptResult(
        text="текст",
        language="ru",
        engine="fake",
        model_id="fake-model",
        audio_seconds=2.0,
        elapsed_seconds=0.0,
    )

    assert result.speed_ratio == 0.0


def test_two_dimensional_audio_is_flattened() -> None:
    transcriber = FakeTranscriber()

    transcriber.transcribe(audio(1.0).reshape(-1, 1), sample_rate=16_000)

    assert transcriber.calls[-1][0] == 16_000
