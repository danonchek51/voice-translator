"""Менеджер загрузки и учёта моделей.

Сеть разрешается только здесь и только по явному действию пользователя.

Главное правило: загрузка обязана попадать туда, где модель будет искать
движок. Поэтому и скачивание, и проверка готовности разветвляются по способу
доставки из реестра — иначе получается «скачано, но не найдено».
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
from voiceflow.core.modelstore.cache import allow_downloads, repo_has_files

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str, float], None]

#: Уведомление о начале загрузки модели: сама модель, её номер и всего штук.
ModelCallback = Callable[["ModelSpec", int, int], None]


class ModelDownloadError(RuntimeError):
    """Загрузка не удалась. Сообщение предназначено пользователю."""


@dataclass(frozen=True, slots=True)
class ModelStatus:
    spec: ModelSpec
    installed: bool
    #: Установлен ли пакет, которому нужна эта модель.
    backend_available: bool
    size_on_disk: int = 0

    @property
    def is_usable(self) -> bool:
        return self.installed and self.backend_available


@dataclass(frozen=True, slots=True)
class DownloadPlan:
    """Что нужно доставить, чтобы пресет заработал."""

    preset: str
    installed: tuple[ModelSpec, ...] = ()
    missing: tuple[ModelSpec, ...] = ()
    manual: tuple[ModelSpec, ...] = ()
    #: Модели, для которых не установлен нужный пакет. Качать их бессмысленно.
    unavailable: tuple[ModelSpec, ...] = ()

    @property
    def total_bytes(self) -> int:
        return sum(spec.size_bytes for spec in self.missing)

    @property
    def total_gb(self) -> float:
        return self.total_bytes / (1024**3)

    @property
    def is_complete(self) -> bool:
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

    # ------------------------------------------------------------------ #
    # Готовность
    # ------------------------------------------------------------------ #

    def is_installed(self, spec: ModelSpec) -> bool:
        """Есть ли файлы модели там, где их будет искать движок."""
        if spec.kind == "files":
            folder = spec.local_path()
            return all((folder / name).is_file() for name in spec.patterns)
        if spec.kind == "hub":
            return repo_has_files(spec.repo, spec.patterns)
        if spec.kind == "whisper":
            return self._whisper_installed(spec)
        if spec.kind in ("file", "url"):
            return spec.local_path().is_file()
        if spec.kind == "zip":
            path = spec.local_path()
            return path.is_dir() and any(path.iterdir())
        # manual
        return spec.local_path().exists()

    @staticmethod
    def _whisper_installed(spec: ModelSpec) -> bool:
        """faster-whisper хранит модель в раскладке кэша Hugging Face."""
        folder = paths.whisper_models_dir() / spec.cache_folder_name
        if not folder.is_dir():
            return False
        return any(folder.rglob("model.bin"))

    def status(self, model_id: str) -> ModelStatus | None:
        spec = self._catalog.by_id(model_id)
        if spec is None:
            return None
        installed = self.is_installed(spec)
        return ModelStatus(
            spec=spec,
            installed=installed,
            backend_available=spec.backend_available(),
            size_on_disk=self._size_on_disk(spec) if installed else 0,
        )

    def downloaded_bytes(self, spec: ModelSpec) -> int:
        """Сколько байт модели уже лежит на диске, считая незавершённые файлы.

        На этом строится индикатор загрузки: библиотека Hugging Face не
        сообщает прогресс наружу, а размер файлов — сообщает.
        """
        if spec.kind == "hub":
            return _payload_size(_hub_cache_root() / spec.cache_folder_name)
        if spec.kind == "whisper":
            return _payload_size(paths.whisper_models_dir() / spec.cache_folder_name)

        target = spec.local_path()
        if spec.kind == "files":
            return _path_size(target)
        if spec.kind == "zip":
            archive = target.parent / f"{target.name}.zip.partial"
            return _path_size(target) + _path_size(archive)

        partial = target.with_suffix(target.suffix + ".partial")
        return _path_size(target) + _path_size(partial)

    def _size_on_disk(self, spec: ModelSpec) -> int:
        if spec.kind == "hub":
            folder = _hub_cache_root() / spec.cache_folder_name
            return _path_size(folder)
        if spec.kind == "whisper":
            return _path_size(paths.whisper_models_dir() / spec.cache_folder_name)
        return _path_size(spec.local_path())

    def list_status(self, preset: str | None = None) -> list[ModelStatus]:
        specs = self._catalog.for_preset(preset) if preset else list(self._catalog.models)
        result: list[ModelStatus] = []
        for spec in specs:
            status = self.status(spec.id)
            if status is not None:
                result.append(status)
        return result

    def installed_llm_path(self, preset: str) -> Path | None:
        """Путь к установленной языковой модели пресета.

        Нужен, чтобы настройки указывали на скачанный файл сами: пустое поле
        ``llm.model_path`` означает «модель не выбрана», и перевод с режимом
        «Инструкция» молча перестают работать после успешной загрузки.
        """
        for spec in self._catalog.for_preset(preset):
            if spec.purpose != "llm":
                continue
            if self.is_installed(spec):
                return spec.local_path()
        return None

    def is_llm_ready(self, preset: str) -> bool:
        """Есть ли и модель, и сервер, который её поднимет."""
        if self.installed_llm_path(preset) is None:
            return False
        runtime = self._catalog.by_id("llama-server")
        return runtime is not None and self.is_installed(runtime)

    def disk_usage(self) -> int:
        root = paths.models_dir()
        return _path_size(root) if root.exists() else 0

    def is_preset_ready(self, preset: str) -> bool:
        """Готов ли пресет к работе: нужен хотя бы один рабочий движок ASR."""
        statuses = self.list_status(preset)
        return any(s.is_usable and s.spec.purpose == "asr" for s in statuses)

    # ------------------------------------------------------------------ #
    # План
    # ------------------------------------------------------------------ #

    def download_plan(self, preset: str) -> DownloadPlan:
        installed: list[ModelSpec] = []
        missing: list[ModelSpec] = []
        manual: list[ModelSpec] = []
        unavailable: list[ModelSpec] = []

        for status in self.list_status(preset):
            spec = status.spec
            if status.installed:
                installed.append(spec)
            elif spec.kind == "manual":
                manual.append(spec)
            elif not status.backend_available:
                # Качать полтора гигабайта под неустановленный пакет незачем.
                unavailable.append(spec)
            else:
                missing.append(spec)

        return DownloadPlan(
            preset=preset,
            installed=tuple(installed),
            missing=tuple(missing),
            manual=tuple(manual),
            unavailable=tuple(unavailable),
        )

    # ------------------------------------------------------------------ #
    # Загрузка
    # ------------------------------------------------------------------ #

    def download(self, model_id: str, progress: ProgressCallback | None = None) -> None:
        """Доставляет модель. Бросает :class:`ModelDownloadError` с понятным текстом."""
        spec = self._catalog.by_id(model_id)
        if spec is None:
            raise ModelDownloadError(f"В реестре нет модели «{model_id}»")
        if spec.kind == "manual":
            raise ModelDownloadError(
                f"«{spec.title}» ставится вручную: {spec.notes or 'ссылки в реестре нет'}"
            )

        with allow_downloads():
            try:
                if spec.kind == "files":
                    self._download_files(spec, progress)
                elif spec.kind == "hub":
                    self._download_hub(spec, progress)
                elif spec.kind == "whisper":
                    self._download_whisper(spec, progress)
                elif spec.kind == "file":
                    self._download_repo_file(spec, progress)
                elif spec.kind == "zip":
                    self._download_zip(spec, progress)
                else:
                    self._download_url(spec, progress)
            except ModelDownloadError:
                raise
            except Exception as exc:
                raise ModelDownloadError(self._explain(spec, exc)) from exc

        if not self.is_installed(spec):
            raise ModelDownloadError(
                f"«{spec.title}»: файлы загружены, но движок их не находит. "
                "Проверьте свободное место и повторите загрузку."
            )

    @staticmethod
    def _explain(spec: ModelSpec, exc: Exception) -> str:
        """Превращает ошибку библиотеки в понятную пользователю причину."""
        text = str(exc)
        lowered = text.lower()

        if "401" in text or "404" in text or "not found" in lowered:
            return (
                f"«{spec.title}»: репозиторий {spec.repo or spec.url} недоступен. "
                "Он мог быть переименован или закрыт — обновите приложение "
                "или загрузите модель вручную и укажите папку."
            )
        if "proxy" in lowered or "certificate" in lowered or "ssl" in lowered:
            return f"«{spec.title}»: соединение отклонено ({text}). Проверьте прокси и антивирус."
        if isinstance(exc, TimeoutError) or "timed out" in lowered:
            return f"«{spec.title}»: сервер не ответил. Повторите — докачка продолжится."
        if "no space" in lowered or "enospc" in lowered:
            return f"«{spec.title}»: на диске не хватает места."
        if "getaddrinfo" in lowered or "name or service" in lowered or "connection" in lowered:
            return f"«{spec.title}»: нет соединения с интернетом."
        return f"«{spec.title}»: {text}"

    def _download_files(self, spec: ModelSpec, progress: ProgressCallback | None) -> None:
        """Несколько файлов репозитория в обычную папку.

        Кэш Hugging Face хранит каждый файл дважды — саму загрузку и копию в
        снимке, потому что без прав на символические ссылки Windows копирует.
        Обычная папка занимает вдвое меньше, переносится на машину без
        интернета простым копированием и не зависит от устройства кэша.
        """
        folder = spec.local_path()
        folder.mkdir(parents=True, exist_ok=True)
        for name in spec.patterns:
            target = folder / name
            if target.is_file():
                continue
            partial = target.with_suffix(target.suffix + ".partial")
            self._fetch(spec, partial, progress, url=file_url(spec, name))
            partial.replace(target)

    def _download_hub(self, spec: ModelSpec, progress: ProgressCallback | None) -> None:
        """Часть репозитория в общий кэш: именно там ищет файлы onnx-asr."""
        snapshot_download = _hf_snapshot_download()
        if progress:
            progress(spec.id, 0.05)
        snapshot_download(repo_id=spec.repo, allow_patterns=list(spec.patterns))
        if progress:
            progress(spec.id, 1.0)

    def _download_whisper(self, spec: ModelSpec, progress: ProgressCallback | None) -> None:
        """Репозиторий целиком в отдельный кэш faster-whisper."""
        snapshot_download = _hf_snapshot_download()
        target = paths.whisper_models_dir()
        target.mkdir(parents=True, exist_ok=True)
        if progress:
            progress(spec.id, 0.05)
        snapshot_download(repo_id=spec.repo, cache_dir=str(target))
        if progress:
            progress(spec.id, 1.0)

    def _download_repo_file(self, spec: ModelSpec, progress: ProgressCallback | None) -> None:
        """Один файл из репозитория — прямой ссылкой, а не через huggingface_hub.

        Причина: репозитории с языковыми моделями лежат в хранилище Xet, и без
        пакета ``hf_xet`` библиотека откатывается на резервный путь, который на
        многогигабайтном файле останавливается почти на нуле. Прямая ссылка
        отдаёт файл ровно, поддерживает докачку и даёт честный прогресс.
        """
        target = spec.local_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(target.suffix + ".partial")

        self._fetch(spec, partial, progress, url=resolve_url(spec))
        if spec.sha256 and not verify_sha256(partial, spec.sha256):
            partial.unlink(missing_ok=True)
            raise ModelDownloadError(f"«{spec.title}»: контрольная сумма не совпала")
        partial.replace(target)

    def _download_url(self, spec: ModelSpec, progress: ProgressCallback | None) -> Path:
        target = spec.local_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(target.suffix + ".partial")
        self._fetch(spec, partial, progress)
        if spec.sha256 and not verify_sha256(partial, spec.sha256):
            partial.unlink(missing_ok=True)
            raise ModelDownloadError(f"«{spec.title}»: контрольная сумма не совпала")
        partial.replace(target)
        return target

    def _download_zip(self, spec: ModelSpec, progress: ProgressCallback | None) -> Path:
        target = spec.local_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        archive = target.parent / f"{target.name}.zip.partial"
        self._fetch(spec, archive, progress)

        if target.exists():
            shutil.rmtree(target) if target.is_dir() else target.unlink()
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(target)
        archive.unlink(missing_ok=True)

        # Архивы моделей обычно содержат один корневой каталог — поднимаем его.
        children = list(target.iterdir())
        if len(children) == 1 and children[0].is_dir():
            nested = children[0]
            for item in nested.iterdir():
                shutil.move(str(item), str(target / item.name))
            nested.rmdir()
        return target

    def _fetch(
        self,
        spec: ModelSpec,
        destination: Path,
        progress: ProgressCallback | None,
        url: str = "",
    ) -> None:
        """Скачивает файл с докачкой с прерванного места."""
        existing = destination.stat().st_size if destination.exists() else 0
        headers = {"User-Agent": "VoiceFlow"}
        if existing:
            headers["Range"] = f"bytes={existing}-"

        request = Request(url or spec.url, headers=headers)
        with urlopen(request, timeout=60) as response:
            if existing and response.status != 206:
                # Сервер не поддержал докачку: начинаем сначала.
                existing = 0
            total = int(response.headers.get("Content-Length") or 0) + existing
            mode = "ab" if existing else "wb"
            with destination.open(mode) as handle:
                done = existing
                while True:
                    chunk = response.read(1024 * 256)
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    if progress and total:
                        progress(spec.id, min(1.0, done / total))
        if progress:
            progress(spec.id, 1.0)

    def download_missing(
        self,
        preset: str,
        progress: ProgressCallback | None = None,
        on_model: ModelCallback | None = None,
    ) -> list[str]:
        """Догружает недостающие модели пресета по очереди.

        ``on_model`` вызывается перед каждой моделью и получает её номер в
        очереди: интерфейсу нужно знать, за какой моделью следить.
        """
        missing = self.download_plan(preset).missing
        downloaded: list[str] = []
        for index, spec in enumerate(missing, start=1):
            if on_model is not None:
                on_model(spec, index, len(missing))
            self.download(spec.id, progress)
            downloaded.append(spec.id)
        return downloaded

    # ------------------------------------------------------------------ #
    # Удаление и офлайн-установка
    # ------------------------------------------------------------------ #

    def delete(self, model_id: str) -> bool:
        spec = self._catalog.by_id(model_id)
        if spec is None or not self.is_installed(spec):
            return False

        if spec.kind == "hub":
            folder = _hub_cache_root() / spec.cache_folder_name
        elif spec.kind == "whisper":
            folder = paths.whisper_models_dir() / spec.cache_folder_name
        else:
            folder = spec.local_path()

        if folder.is_dir():
            shutil.rmtree(folder, ignore_errors=True)
        else:
            folder.unlink(missing_ok=True)
        logger.info("Удалена модель %s", model_id)
        return True

    def import_from_folder(self, preset: str, source_dir: Path) -> list[str]:
        """Забирает недостающие модели пресета из заранее подготовленной папки.

        Путь для машины без интернета. Работает только для моделей, которые
        живут по предсказуемому пути: содержимое кэша Hugging Face так не
        переносится.
        """
        if not source_dir.is_dir():
            raise NotADirectoryError(source_dir)

        available = {item.name: item for item in source_dir.iterdir()}
        imported: list[str] = []
        for spec in self.download_plan(preset).missing:
            if spec.kind in ("hub", "whisper"):
                continue
            candidate = available.get(Path(spec.relative_path).name)
            if candidate is None:
                continue
            self._copy_into_place(spec, candidate)
            imported.append(spec.id)
            logger.info("Модель %s взята из %s", spec.id, candidate)
        return imported

    #: Оставлено методом класса: так проверку удобно вызывать из диагностики.
    verify_sha256 = staticmethod(lambda path, expected: verify_sha256(path, expected))

    @staticmethod
    def _copy_into_place(spec: ModelSpec, source: Path) -> None:
        target = spec.local_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)


_MISSING_HUB = (
    "Для загрузки с Hugging Face нужен пакет huggingface-hub. "
    "Выполните: uv sync --extra asr"
)


def _hf_snapshot_download():  # type: ignore[no-untyped-def]
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise ModelDownloadError(_MISSING_HUB) from exc
    return snapshot_download


def _hub_cache_root() -> Path:
    from voiceflow.core.modelstore.cache import hub_cache_root

    return hub_cache_root()


def verify_sha256(path: Path, expected: str) -> bool:
    """Сверяет контрольную сумму файла. Пустое ожидание означает «не проверять»."""
    if not expected:
        return True
    if path.is_dir():
        return True
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower() == expected.lower()


def resolve_url(spec: ModelSpec) -> str:
    """Прямая ссылка на файл в репозитории Hugging Face."""
    return file_url(spec, spec.patterns[0])


def file_url(spec: ModelSpec, name: str) -> str:
    """Прямая ссылка на конкретный файл репозитория."""
    return f"https://huggingface.co/{spec.repo}/resolve/main/{name}"


def _path_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(child.stat().st_size for child in path.rglob("*") if child.is_file())


def _payload_size(cache_folder: Path) -> int:
    """Объём скачанных данных в каталоге кэша Hugging Face.

    Считается только ``blobs``: в ``snapshots`` лежат те же данные повторно,
    потому что на Windows без прав на символические ссылки библиотека копирует
    файлы. Учёт обеих папок дал бы двести процентов на индикаторе.
    """
    blobs = cache_folder / "blobs"
    return _path_size(blobs) if blobs.exists() else _path_size(cache_folder)


def guess_extension(url: str) -> str:
    """Расширение файла из ссылки. Нужно для выбора способа распаковки."""
    return Path(urlparse(url).path).suffix.lower()
