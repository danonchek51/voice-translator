"""Реестр и менеджер локальных моделей."""

from voiceflow.core.models.catalog import (
    ModelCatalog,
    ModelSpec,
    load_catalog,
    validate_spec,
)
from voiceflow.core.models.manager import (
    DownloadPlan,
    ModelDownloadError,
    ModelManager,
    ModelStatus,
)
from voiceflow.core.models.presets import (
    DEFAULT_PRESET,
    PRESET_SPECS,
    PresetSpec,
    apply_preset,
    get_preset,
    list_presets,
)

__all__ = [
    "DEFAULT_PRESET",
    "PRESET_SPECS",
    "DownloadPlan",
    "ModelCatalog",
    "ModelDownloadError",
    "ModelManager",
    "ModelSpec",
    "ModelStatus",
    "PresetSpec",
    "apply_preset",
    "get_preset",
    "list_presets",
    "load_catalog",
    "validate_spec",
]
