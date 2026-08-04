"""Реестр моделей из config/models.toml."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from voiceflow import paths

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ModelSpec:
    id: str
    title: str
    purpose: str
    presets: tuple[str, ...]
    size_bytes: int
    sha256: str
    url: str
    relative_path: str
    required: bool = False
    notes: str = ""

    def local_path(self) -> Path:
        return paths.models_dir() / self.relative_path

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)


@dataclass(frozen=True, slots=True)
class ModelCatalog:
    models: tuple[ModelSpec, ...] = field(default_factory=tuple)

    def by_id(self, model_id: str) -> ModelSpec | None:
        for model in self.models:
            if model.id == model_id:
                return model
        return None

    def for_preset(self, preset: str) -> list[ModelSpec]:
        return [m for m in self.models if preset in m.presets or m.required]

    def total_size(self, preset: str) -> int:
        return sum(m.size_bytes for m in self.for_preset(preset))


def load_catalog(path: Path | None = None) -> ModelCatalog:
    catalog_path = path or (paths.config_dir() / "models.toml")
    if not catalog_path.is_file():
        logger.warning("Реестр моделей не найден: %s", catalog_path)
        return ModelCatalog()

    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover
        import tomli as tomllib  # type: ignore

    data = tomllib.loads(catalog_path.read_text(encoding="utf-8"))
    models: list[ModelSpec] = []
    for raw in data.get("models", []):
        if not isinstance(raw, dict):
            continue
        models.append(_parse_model(raw))
    return ModelCatalog(models=tuple(models))


def _parse_model(raw: dict[str, Any]) -> ModelSpec:
    presets = raw.get("presets") or []
    return ModelSpec(
        id=str(raw.get("id", "")),
        title=str(raw.get("title", "")),
        purpose=str(raw.get("purpose", "")),
        presets=tuple(str(p) for p in presets),
        size_bytes=int(raw.get("size_bytes") or 0),
        sha256=str(raw.get("sha256") or ""),
        url=str(raw.get("url") or ""),
        relative_path=str(raw.get("relative_path") or ""),
        required=bool(raw.get("required", False)),
        notes=str(raw.get("notes") or ""),
    )
