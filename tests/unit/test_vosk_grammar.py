"""Грамматика Vosk должна содержать целые фразы, а не отдельные слова."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from voiceflow.core.wake.vosk_grammar import VoskGrammarDetector


class _FakeRecognizer:
    def __init__(self, model: object, sample_rate: int, grammar: str) -> None:
        self.grammar = grammar
        self.model = model
        self.sample_rate = sample_rate


def test_grammar_uses_full_phrases(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: list[str] = []

    class FakeModel:
        def __init__(self, path: str) -> None:
            self.path = path

    def fake_recognizer(model: object, sample_rate: int, grammar: str) -> _FakeRecognizer:
        captured.append(grammar)
        return _FakeRecognizer(model, sample_rate, grammar)

    model_dir = tmp_path / "vosk-model-small-ru"
    model_dir.mkdir()
    detector = VoskGrammarDetector(model_dir=model_dir)
    monkeypatch.setattr(detector, "is_available", lambda: True)
    monkeypatch.setattr("vosk.Model", FakeModel)
    monkeypatch.setattr("vosk.KaldiRecognizer", fake_recognizer)

    detector.set_phrases(["слушай сюда", "конец записи"])

    assert captured
    phrases = json.loads(captured[-1])
    assert "слушай сюда" in phrases
    assert "конец записи" in phrases
    assert "слушай" not in phrases or "слушай сюда" in phrases
    # Отдельные слова фразы не должны быть самостоятельными альтернативами.
    assert phrases.count("слушай") == 0
    assert phrases.count("сюда") == 0
