"""Интерфейс локальной языковой модели.

Модель живёт в отдельном процессе с HTTP-интерфейсом на петлевом адресе.
Такое разделение выбрано намеренно:

* не нужно собирать привязки к CUDA внутри Python — самая частая причина
  неработающей установки на чужой машине;
* падение модели не роняет приложение;
* тот же интерфейс позволяет подключить уже установленные Ollama или
  LM Studio вместо встроенного сервера.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class LlmError(RuntimeError):
    """Общая ошибка обращения к модели."""


class LlmUnavailableError(LlmError):
    """Сервер модели не запущен или не отвечает."""


class LlmTimeoutError(LlmError):
    """Модель не ответила за отведённое время."""


class LlmRefusedError(LlmError):
    """Обращение заблокировано: например, адрес не петлевой."""


@dataclass(frozen=True, slots=True)
class LlmInfo:
    """Сведения о подключённой модели для диагностики."""

    endpoint: str
    model: str
    available: bool
    detail: str = ""


class LlmClient(ABC):
    """Минимальный интерфейс: одно обращение — один ответ."""

    @abstractmethod
    def info(self) -> LlmInfo:
        """Состояние подключения. Не должно бросать исключений."""

    @abstractmethod
    def is_available(self) -> bool:
        """Быстрая проверка доступности без генерации."""

    @abstractmethod
    def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> str:
        """Отправляет запрос и возвращает текст ответа."""

    def close(self) -> None:
        """Освобождает ресурсы. По умолчанию ничего не делает."""
        return None
