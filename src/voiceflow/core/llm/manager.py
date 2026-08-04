"""Подключение к локальной языковой модели.

Один объект отвечает на вопрос «есть ли сейчас модель и как к ней обратиться».
Он же решает, запускать ли собственный сервер или использовать чужой, и
переживает смену настроек без перезапуска приложения.

Модель принципиально необязательна: без неё приложение работает на
детерминированной очистке, просто хуже переводит и структурирует.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path

from voiceflow.core.llm.base import LlmClient, LlmInfo, LlmRefusedError
from voiceflow.core.llm.llama_server import (
    LlamaServer,
    LlamaServerError,
    ServerConfig,
    is_installed,
)
from voiceflow.core.llm.openai_compat import OpenAiCompatibleClient
from voiceflow.core.settings.schema import LlmSettings

logger = logging.getLogger(__name__)


class LlmManager:
    """Владелец клиента и, при необходимости, собственного сервера."""

    def __init__(self, settings_provider: Callable[[], LlmSettings]) -> None:
        self._settings_provider = settings_provider
        self._lock = threading.RLock()
        self._client: LlmClient | None = None
        self._server: LlamaServer | None = None
        self._last_error = ""

    @property
    def last_error(self) -> str:
        return self._last_error

    def info(self) -> LlmInfo:
        """Состояние для вкладки диагностики. Не запускает сервер."""
        settings = self._settings_provider()
        with self._lock:
            if self._client is not None:
                return self._client.info()
        return LlmInfo(
            endpoint=settings.endpoint,
            model=Path(settings.model_path).name or "не выбрана",
            available=False,
            detail=self._last_error or "модель не подключена",
        )

    def client(self) -> LlmClient | None:
        """Готовый клиент или ``None``, если модель недоступна."""
        with self._lock:
            if self._client is not None and self._client.is_available():
                return self._client
            return self._connect()

    def ensure_started(self) -> bool:
        """Поднимает встроенный сервер, если он нужен и ещё не запущен."""
        return self.client() is not None

    def shutdown(self) -> None:
        """Останавливает сервер и освобождает видеопамять."""
        with self._lock:
            if self._client is not None:
                self._client.close()
                self._client = None
            if self._server is not None:
                self._server.stop()
                self._server = None

    def reload(self) -> None:
        """Применяет изменившиеся настройки при следующем обращении."""
        self.shutdown()
        self._last_error = ""

    # ------------------------------------------------------------------ #
    # Внутреннее
    # ------------------------------------------------------------------ #

    def _connect(self) -> LlmClient | None:
        settings = self._settings_provider()

        if settings.backend == "external":
            return self._connect_external(settings)
        return self._connect_builtin(settings)

    def _connect_external(self, settings: LlmSettings) -> LlmClient | None:
        client = self._make_client(settings.endpoint, settings)
        if client is None:
            return None
        if not client.is_available():
            client.close()
            self._last_error = (
                f"По адресу {settings.endpoint} никто не отвечает. "
                "Запустите Ollama или LM Studio либо переключитесь на встроенный сервер."
            )
            logger.info("Внешний сервер модели недоступен: %s", settings.endpoint)
            return None
        self._client = client
        self._last_error = ""
        return client

    def _connect_builtin(self, settings: LlmSettings) -> LlmClient | None:
        if not settings.model_path:
            self._last_error = (
                "Модель не выбрана. Откройте настройки, вкладка «Модели»."
            )
            return None
        if not is_installed():
            self._last_error = (
                "Локальный сервер модели не установлен. "
                "Откройте настройки, вкладка «Модели»."
            )
            return None

        # Уже запущенный экземпляр (например, после перезапуска приложения)
        # переиспользуем, а не поднимаем второй.
        existing = self._make_client(settings.endpoint, settings)
        if existing is not None and existing.is_available():
            self._client = existing
            self._last_error = ""
            return existing
        if existing is not None:
            existing.close()

        server = LlamaServer(
            ServerConfig(
                model_path=Path(settings.model_path),
                port=_port_of(settings.endpoint),
                n_gpu_layers=settings.n_gpu_layers,
                context_size=settings.context_size,
            )
        )
        try:
            server.start()
        except LlamaServerError as exc:
            self._last_error = str(exc)
            logger.warning("Сервер модели не запущен: %s", exc)
            return None

        client = self._make_client(server.endpoint, settings)
        if client is None:
            server.stop()
            return None

        self._server = server
        self._client = client
        self._last_error = ""
        return client

    def _make_client(self, endpoint: str, settings: LlmSettings) -> LlmClient | None:
        try:
            return OpenAiCompatibleClient(
                endpoint=endpoint,
                model=Path(settings.model_path).stem or "local",
                timeout=settings.timeout_s,
            )
        except LlmRefusedError as exc:
            self._last_error = str(exc)
            logger.error("%s", exc)
            return None


def _port_of(endpoint: str) -> int:
    from urllib.parse import urlparse

    try:
        parsed = urlparse(endpoint)
    except ValueError:
        return 8079
    return parsed.port or 8079
