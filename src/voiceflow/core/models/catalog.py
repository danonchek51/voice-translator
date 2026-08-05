"""Реестр моделей из ``config/models.toml``.

Запись реестра описывает не просто ссылку, а способ доставки: каждый движок
ищет свои файлы в своём месте, и загрузка обязана попадать именно туда.
Иначе скачивание «проходит», а приложение продолжает считать модель
отсутствующей.

Способы доставки (поле ``kind``):

* ``hub`` — часть репозитория Hugging Face в общий кэш моделей. Так ищет
  файлы onnx-asr, поэтому GigaAM доставляется только этим способом;
* ``whisper`` — репозиторий целиком в отдельный кэш faster-whisper;
* ``file`` — один файл из репозитория по конкретному пути;
* ``url`` — прямая ссылка на файл;
* ``zip`` — архив по ссылке с распаковкой в каталог;
* ``manual`` — ставится руками, ссылки нет.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from voiceflow import paths

logger = logging.getLogger(__name__)

#: Допустимые способы доставки.
KINDS = ("files", "hub", "whisper", "file", "url", "zip", "manual")


@dataclass(frozen=True, slots=True)
class ModelSpec:
    id: str
    title: str
    purpose: str
    presets: tuple[str, ...]
    size_bytes: int
    kind: str = "manual"
    #: Репозиторий Hugging Face для способов ``hub``, ``whisper`` и ``file``.
    repo: str = ""
    #: Имена нужных файлов внутри репозитория. Для ``hub`` они же служат
    #: признаком установленности, для ``file`` берётся первый.
    patterns: tuple[str, ...] = ()
    #: Прямая ссылка для ``url`` и ``zip``.
    url: str = ""
    #: Путь внутри каталога моделей для ``file``, ``url``, ``zip`` и ``manual``.
    relative_path: str = ""
    #: Модуль, без которого модель бесполезна: движок не установлен.
    requires: str = ""
    sha256: str = ""
    required: bool = False
    notes: str = ""

    def local_path(self) -> Path:
        return paths.models_dir() / self.relative_path

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)

    @property
    def cache_folder_name(self) -> str:
        """Имя каталога кэша Hugging Face для этого репозитория."""
        return f"models--{self.repo.replace('/', '--')}"

    def backend_available(self) -> bool:
        """Установлен ли пакет, которому нужна эта модель."""
        if not self.requires:
            return True
        import importlib.util

        return importlib.util.find_spec(self.requires) is not None


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
    """Читает реестр. Пустой реестр при отсутствии файла — не ошибка запуска."""
    catalog_path = path or (paths.config_dir() / "models.toml")
    if not catalog_path.is_file():
        logger.warning("Реестр моделей не найден: %s", catalog_path)
        return ModelCatalog()

    import tomllib

    try:
        data = tomllib.loads(catalog_path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as exc:
        logger.error("Реестр моделей не прочитан: %s", exc)
        return ModelCatalog()

    models: list[ModelSpec] = []
    for raw in data.get("models", []):
        if not isinstance(raw, dict):
            continue
        spec = _parse_model(raw)
        problem = validate_spec(spec)
        if problem:
            logger.warning("Запись реестра «%s» пропущена: %s", spec.id, problem)
            continue
        models.append(spec)
    return ModelCatalog(models=tuple(models))


def validate_spec(spec: ModelSpec) -> str:
    """Проверяет, что запись описана полностью. Пустая строка — всё в порядке.

    Нужна, чтобы опечатка в реестре обнаруживалась при загрузке, а не
    посреди скачивания на машине пользователя.
    """
    if not spec.id:
        return "не задан идентификатор"
    if spec.kind not in KINDS:
        return f"неизвестный способ доставки «{spec.kind}»"

    if spec.kind in ("files", "hub", "whisper", "file") and not spec.repo:
        return "не задан репозиторий"
    if spec.kind in ("files", "hub") and not spec.patterns:
        return "не заданы имена файлов"
    if spec.kind == "file" and not spec.patterns:
        return "не задано имя файла"
    if spec.kind in ("url", "zip") and not spec.url:
        return "не задана ссылка"
    if spec.kind in ("files", "file", "url", "zip", "manual") and not spec.relative_path:
        return "не задан путь внутри каталога моделей"
    return ""


def _parse_model(raw: dict[str, Any]) -> ModelSpec:
    return ModelSpec(
        id=str(raw.get("id", "")),
        title=str(raw.get("title", "")),
        purpose=str(raw.get("purpose", "")),
        presets=tuple(str(p) for p in (raw.get("presets") or ())),
        size_bytes=int(raw.get("size_bytes") or 0),
        kind=str(raw.get("kind") or "manual"),
        repo=str(raw.get("repo") or ""),
        patterns=tuple(str(p) for p in (raw.get("patterns") or ())),
        url=str(raw.get("url") or ""),
        relative_path=str(raw.get("relative_path") or ""),
        requires=str(raw.get("requires") or ""),
        sha256=str(raw.get("sha256") or ""),
        required=bool(raw.get("required", False)),
        notes=str(raw.get("notes") or ""),
    )
