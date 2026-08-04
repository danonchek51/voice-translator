"""Запуск и остановка встроенного ``llama-server``.

Сервер — обычный исполняемый файл из официальной сборки llama.cpp. Он лежит
рядом с моделями и обновляется независимо от приложения. Такой путь выбран
вместо привязок внутри Python: готовые пакеты с поддержкой CUDA существуют
не для всех версий Python и регулярно ломаются, а сборка из исходников
требует установленных компилятора и CUDA Toolkit.

Приложение не обязано запускать сервер само: в настройках можно указать
уже работающий Ollama или LM Studio.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from voiceflow import paths

logger = logging.getLogger(__name__)

EXECUTABLE_NAME = "llama-server.exe" if sys.platform == "win32" else "llama-server"

#: Сколько ждать готовности сервера после запуска.
STARTUP_TIMEOUT_SECONDS = 120.0
STARTUP_POLL_SECONDS = 0.5

#: Сколько ждать корректного завершения перед принудительным.
SHUTDOWN_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class ServerConfig:
    """Параметры запуска сервера."""

    model_path: Path
    port: int = 8079
    n_gpu_layers: int = 999
    context_size: int = 4096
    #: Ноль означает «по числу ядер».
    threads: int = 0


class LlamaServerError(RuntimeError):
    """Сервер не удалось запустить."""


def executable_path() -> Path:
    """Путь к исполняемому файлу сервера внутри каталога моделей."""
    return paths.runtime_dir() / "llama.cpp" / EXECUTABLE_NAME


def is_installed() -> bool:
    return executable_path().is_file()


class LlamaServer:
    """Владелец дочернего процесса сервера."""

    def __init__(self, config: ServerConfig, executable: Path | None = None) -> None:
        self._config = config
        self._executable = executable or executable_path()
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = threading.RLock()

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self._config.port}"

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None

    def command(self) -> list[str]:
        """Аргументы запуска. Вынесено отдельно ради тестируемости."""
        arguments = [
            str(self._executable),
            "--model",
            str(self._config.model_path),
            "--host",
            "127.0.0.1",
            "--port",
            str(self._config.port),
            "--ctx-size",
            str(self._config.context_size),
            "--n-gpu-layers",
            str(self._config.n_gpu_layers),
        ]
        if self._config.threads > 0:
            arguments += ["--threads", str(self._config.threads)]
        return arguments

    def start(self, wait_ready: bool = True) -> None:
        """Запускает сервер. Повторный вызов при живом процессе ничего не делает."""
        with self._lock:
            if self.is_running:
                return
            if not self._executable.is_file():
                raise LlamaServerError(
                    f"Не найден {self._executable.name}. Откройте настройки, "
                    "вкладка «Модели», и установите локальный сервер."
                )
            if not self._config.model_path.is_file():
                raise LlamaServerError(
                    f"Файл модели не найден: {self._config.model_path}"
                )

            logger.info("Запуск локального сервера модели на порту %s", self._config.port)
            try:
                self._process = subprocess.Popen(
                    self.command(),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=str(self._executable.parent),
                    creationflags=_no_window_flag(),
                )
            except OSError as exc:
                raise LlamaServerError(f"Не удалось запустить сервер модели: {exc}") from exc

        if wait_ready and not self.wait_until_ready():
            self.stop()
            raise LlamaServerError(
                "Сервер модели не ответил за отведённое время. "
                "Возможно, не хватает видеопамяти для выбранной модели."
            )

    def wait_until_ready(self, timeout: float = STARTUP_TIMEOUT_SECONDS) -> bool:
        """Ждёт, пока сервер начнёт отвечать на проверку здоровья."""
        from voiceflow.core.llm.openai_compat import OpenAiCompatibleClient

        client = OpenAiCompatibleClient(self.endpoint)
        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                if not self.is_running:
                    logger.error("Процесс сервера модели завершился при запуске")
                    return False
                if client.is_available():
                    logger.info("Сервер модели готов")
                    return True
                time.sleep(STARTUP_POLL_SECONDS)
            return False
        finally:
            client.close()

    def stop(self) -> None:
        """Останавливает сервер, освобождая видеопамять."""
        with self._lock:
            process = self._process
            self._process = None

        if process is None or process.poll() is not None:
            return

        logger.info("Остановка локального сервера модели")
        process.terminate()
        try:
            process.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            logger.warning("Сервер модели не завершился сам, снимаю принудительно")
            process.kill()
            process.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS)


def _no_window_flag() -> int:
    """Не показывать окно консоли на Windows."""
    if sys.platform == "win32":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0
