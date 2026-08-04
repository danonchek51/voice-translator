"""Клиент к локальному серверу с OpenAI-совместимым интерфейсом.

Подходит и к встроенному ``llama-server``, и к Ollama, и к LM Studio: у всех
одинаковый путь ``/v1/chat/completions``.

Здесь единственное место в рантайме, где приложение обращается по сети,
и обращение жёстко ограничено петлевым адресом. Попытка указать внешний
хост отклоняется: пользователь выбрал локальную работу, и нарушать это
молча нельзя.
"""

from __future__ import annotations

import ipaddress
import logging
from typing import Any
from urllib.parse import urlparse

import httpx

from voiceflow.core.llm.base import (
    LlmClient,
    LlmError,
    LlmInfo,
    LlmRefusedError,
    LlmTimeoutError,
    LlmUnavailableError,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0
HEALTH_TIMEOUT = 1.5

#: Имена, которые считаются локальными помимо числовых петлевых адресов.
LOCAL_HOSTNAMES = frozenset({"localhost", "127.0.0.1", "::1", ""})


def is_loopback(endpoint: str) -> bool:
    """Проверяет, что адрес указывает на эту же машину."""
    try:
        parsed = urlparse(endpoint)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if host in LOCAL_HOSTNAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class OpenAiCompatibleClient(LlmClient):
    """Обращение к локальному серверу моделей."""

    def __init__(
        self,
        endpoint: str,
        model: str = "local",
        timeout: float = DEFAULT_TIMEOUT,
        allow_remote: bool = False,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._allow_remote = allow_remote
        self._client: httpx.Client | None = None

        if not allow_remote and not is_loopback(self._endpoint):
            raise LlmRefusedError(
                f"Адрес {endpoint} не является локальным. Основной режим работы "
                "не обращается в интернет; укажите адрес на 127.0.0.1."
            )

    @property
    def endpoint(self) -> str:
        return self._endpoint

    def info(self) -> LlmInfo:
        available = self.is_available()
        return LlmInfo(
            endpoint=self._endpoint,
            model=self._model,
            available=available,
            detail="" if available else "сервер модели не отвечает",
        )

    def is_available(self) -> bool:
        for path in ("/health", "/v1/models"):
            try:
                response = self._http().get(f"{self._endpoint}{path}", timeout=HEALTH_TIMEOUT)
            except httpx.HTTPError:
                continue
            if response.status_code < 500:
                return True
        return False

    def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> str:
        messages: list[dict[str, str]] = []
        if system.strip():
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            # Нулевая температура: обработка текста должна быть повторяемой.
            "temperature": temperature,
            "stream": False,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        try:
            response = self._http().post(
                f"{self._endpoint}/v1/chat/completions",
                json=payload,
                timeout=timeout or self._timeout,
            )
        except httpx.TimeoutException as exc:
            raise LlmTimeoutError(
                f"Модель не ответила за {timeout or self._timeout:.0f} с"
            ) from exc
        except httpx.HTTPError as exc:
            raise LlmUnavailableError(f"Сервер модели недоступен: {exc}") from exc

        if response.status_code >= 400:
            raise LlmError(
                f"Сервер модели вернул ошибку {response.status_code}: "
                f"{response.text[:200]}"
            )

        return _extract_text(response)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(trust_env=False)
        return self._client


def _extract_text(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError as exc:
        raise LlmError("Сервер модели вернул не JSON") from exc

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LlmError("В ответе сервера нет вариантов ответа")

    message = choices[0].get("message") or {}
    content = message.get("content")
    if not isinstance(content, str):
        raise LlmError("В ответе сервера нет текста")
    return content
