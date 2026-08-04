"""Голосовая активация."""

from voiceflow.core.wake.base import DetectorInfo, WakeHit, WakeWordDetector
from voiceflow.core.wake.matcher import normalize_phrase, phrase_risk, phrases_match
from voiceflow.core.wake.registry import create_wake_detector
from voiceflow.core.wake.service import WakeService

__all__ = [
    "DetectorInfo",
    "WakeHit",
    "WakeService",
    "WakeWordDetector",
    "create_wake_detector",
    "normalize_phrase",
    "phrase_risk",
    "phrases_match",
]
