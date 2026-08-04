"""Распознавание речи за единым интерфейсом."""

from voiceflow.core.asr.base import (
    BackendUnavailableError,
    EngineInfo,
    ModelNotReadyError,
    Transcriber,
    TranscriberError,
    TranscriptResult,
)
from voiceflow.core.asr.registry import (
    EngineSelection,
    ResolvedTranscriber,
    TranscriberRegistry,
    detect_device,
    select_engine,
)

__all__ = [
    "BackendUnavailableError",
    "EngineInfo",
    "EngineSelection",
    "ModelNotReadyError",
    "ResolvedTranscriber",
    "Transcriber",
    "TranscriberError",
    "TranscriberRegistry",
    "TranscriptResult",
    "detect_device",
    "select_engine",
]
