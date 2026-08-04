"""Менеджер загрузки и учёта моделей.

Сеть разрешается только здесь и только по явному действию пользователя.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from voiceflow import paths
from voiceflow.core.models.catalog import ModelCatalog, ModelSpec, load_catalog
from voiceflow.core.modelstore.cache import allow_downloads

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str, float], None]


@dataclass(frozen=True, slots=True)
class ModelStatus:
    spec: ModelSpec
    installed: bool
    path: Path
    size_on_disk: int
    sha_ok: bool | None


@dataclass(frozen=True, slots=True)
class DownloadPlan:
    """Что нужно доставить, чтобы пресет заработал.

    Модели без ссылки в реестре попадают в :attr:`manual`: их нельзя скачать
    автоматически, но и молча пропускать нельзя — пользователь должен узнать,
    что установить руками.
    """

    preset: str
    installed: tuple[ModelSpec, ...] = ()
    missing: tuple[ModelSpec, ...] = ()
    manual: tuple[ModelSpec, ...] = ()

    @property
    def total_bytes(self) -> int:
        """Сколько предстоит скачать."""
        return sum(spec.size_bytes for spec in self.missing)

    @property
    def total_gb(self) -> float:
        return self.total_bytes / (1024**3)

    @property
    def is_complete(self) -> bool:
        """Всё, что можно скачать, уже на диске."""
        return not self.missing


class ModelManager:
    """Загрузка, проверка и удаление моделей по реестру."""

    def __init__(self, catalog: ModelCatalog | None = None) -> None:
        self._catalog = catalog or load_catalog()

    @property
    def catalog(self) -> ModelCatalog:
        return self._catalog

    def reload(self) -> None:
        self._catalog = load_catalog()

    def status(self, model_id: str) -> ModelStatus | None:
        spec = self._catalog.by_id(model_id)
        if spec is None:
            return None
        path = spec.local_path()
        installed = path.exists()
        size = _path_size(path) if installed else 0
        sha_ok: bool | None = None
        if installed and spec.sha256:
            sha_ok = self.verify_sha256(path, spec.sha256)
        return ModelStatus(
            spec=spec,
            installed=installed,
            path=path,
            size_on_disk=size,
            sha_ok=sha_ok,
        )

    def list_status(self, preset: str | None = None) -> list[ModelStatus]:
        specs = self._catalog.for_preset(preset) if preset else list(self._catalog.models)
        result: list[ModelStatus] = []
        for spec in specs:
            status = self.status(spec.id)
            if status is not None:
                result.append(status)
        return result

    def disk_usage(self) -> int:
        root = paths.models_dir()
        if not root.exists():
            return 0
        return _path_size(root)

    def download_plan(self, preset: str) -> DownloadPlan:
        """Разбирает состав пресета на уже установленное и недостающее."""
        installed: list[ModelSpec] = []
        missing: list[ModelSpec] = []
        manual: list[ModelSpec] = []

        for status in self.list_status(preset):
            if status.installed:
                installed.append(status.spec)
            elif status.spec.url:
                missing.append(status.spec)
            else:
                manual.append(status.spec)

        return DownloadPlan(
            preset=preset,
            installed=tuple(installed),
            missing=tuple(missing),
            manual=tuple(manual),
        )

    def download_missing(
        self,
        preset: str,
        progress: ProgressCallback | None = None,
    ) -> list[Path]:
        """Догружает недостающие модели пресета по очереди.

        Первая же неудача прерывает загрузку: продолжать вслепую нельзя, зато
        повторный вызов подхватит недокачанные файлы с того же места.
        """
        plan = self.download_plan(preset)
        downloaded: list[Path] = []
        for spec in plan.missing:
            downloaded.append(self.download(spec.id, progress))
        return downloaded

    def is_preset_ready(self, preset: str) -> bool:
        asr_ready = any(
            s.installed and s.spec.purpose == "asr" for s in self.list_status(preset)
        )
        if preset == "light":
            return asr_ready
        llm_ready = any(
            s.installed and s.spec.purpose == "llm" for s in self.list_status(preset)
        )
        return asr_ready and llm_ready

    def download(
        self,
        model_id: str,
        progress: ProgressCallback | None = None,
    ) -> Path:
        spec = self._catalog.by_id(model_id)
        if spec is None:
            raise KeyError(f"Неизвестная модель: {model_id}")
        if not spec.url:
            raise RuntimeError(
                f"Для «{spec.title}» не задан URL. Укажите локальную папку или "
                "настройте внешний сервер LLM."
            )

        target = spec.local_path()
        target.parent.mkdir(parents=True, exist_ok=True)

        with allow_downloads():
            if spec.url.startswith("hf://"):
                path = self._download_hf(spec, progress)
            else:
                path = self._download_url(spec, progress)

        if spec.sha256 and not self.verify_sha256(path, spec.sha256):
            raise RuntimeError(f"Контрольная сумма не совпала для {spec.id}")
        return path

    def _download_url(self, spec: ModelSpec, progress: ProgressCallback | None) -> Path:
        target = spec.local_path()
        parsed = urlparse(spec.url)
        is_zip = parsed.path.lower().endswith(".zip")
        download_path = target.with_suffix(target.suffix + ".partial")
        if is_zip:
            download_path = target.parent / (target.name + ".zip.partial")

        existing = download_path.stat().st_size if download_path.exists() else 0
        headers = {}
        if existing:
            headers["Range"] = f"bytes={existing}-"

        request = Request(spec.url, headers=headers)
        with urlopen(request, timeout=60) as response:
            total = int(response.headers.get("Content-Length") or 0) + existing
            mode = "ab" if existing else "wb"
            with download_path.open(mode) as handle:
                done = existing
                while True:
                    chunk = response.read(1024 * 256)
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    if progress and total:
                        progress(spec.id, min(1.0, done / total))

        if is_zip:
            final_zip = download_path.with_suffix("")
            download_path.replace(final_zip)
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            target.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(final_zip) as archive:
                archive.extractall(target)
            final_zip.unlink(missing_ok=True)
            children = list(target.iterdir())
            if len(children) == 1 and children[0].is_dir():
                nested = children[0]
                for item in nested.iterdir():
                    shutil.move(str(item), str(target / item.name))
                nested.rmdir()
            return target

        download_path.replace(target)
        if progress:
            progress(spec.id, 1.0)
        return target

    def _download_hf(self, spec: ModelSpec, progress: ProgressCallback | None) -> Path:
        repo_id = spec.url.removeprefix("hf://")
        target = spec.local_path()
        try:
            from huggingface_hub import snapshot_download
        except ImportError as exc:
            raise RuntimeError(
                "Для загрузки с Hugging Face нужен пакет huggingface-hub. "
                "Выполните: uv sync --extra asr"
            ) from exc

        if progress:
            progress(spec.id, 0.05)
        # local_dir кладёт настоящие файлы, а не ссылки на общий кэш:
        # каталог моделей должен переноситься вместе с portable-версией.
        snapshot = snapshot_download(repo_id=repo_id, local_dir=str(target))
        if progress:
            progress(spec.id, 1.0)
        return Path(snapshot)

    def delete(self, model_id: str) -> bool:
        status = self.status(model_id)
        if status is None or not status.installed:
            return False
        path = status.path
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
        logger.info("Удалена модель %s", model_id)
        return True

    def import_from_folder(self, preset: str, source_dir: Path) -> list[str]:
        """Забирает недостающие модели пресета из заранее подготовленной папки.

        Это путь для машины без интернета. Совпадение ищется по имени файла
        или каталога из реестра, вложенность не разбирается: пользователь
        кладёт рядом ровно то, что перечислено в списке моделей.
        """
        if not source_dir.is_dir():
            raise NotADirectoryError(source_dir)

        available = {item.name: item for item in source_dir.iterdir()}
        imported: list[str] = []
        for spec in self.download_plan(preset).missing:
            candidate = available.get(Path(spec.relative_path).name)
            if candidate is None:
                continue
            self.import_local(spec.id, candidate)
            imported.append(spec.id)
            logger.info("Модель %s взята из %s", spec.id, candidate)
        return imported

    def import_local(self, model_id: str, source: Path) -> Path:
        spec = self._catalog.by_id(model_id)
        if spec is None:
            raise KeyError(model_id)
        target = spec.local_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
        return target

    @staticmethod
    def verify_sha256(path: Path, expected: str) -> bool:
        if not expected:
            return True
        if path.is_dir():
            return True
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest().lower() == expected.lower()


def _path_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            total += child.stat().st_size
    return total
