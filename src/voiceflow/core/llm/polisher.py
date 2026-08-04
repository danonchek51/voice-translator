"""Полировка текста языковой моделью.

Связывает три части: инструкцию из файла, клиент модели и шаг обработки.
Проверкой ответа занимается guard в текстовом конвейере — там же, где живут
метки защищённых фрагментов.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from voiceflow.core.llm.base import LlmClient, LlmError
from voiceflow.core.llm.prompts import PromptError, PromptLibrary
from voiceflow.core.text.modes import ProcessingStep

logger = logging.getLogger(__name__)

#: Запас по длине ответа относительно запроса.
MAX_TOKENS_MULTIPLIER = 3
MIN_MAX_TOKENS = 256


class LlmPolisher:
    """Вызов модели по инструкции выбранного шага."""

    def __init__(
        self,
        client_provider: Callable[[], LlmClient | None],
        library: PromptLibrary | None = None,
        timeout_provider: Callable[[], float] | None = None,
    ) -> None:
        self._client_provider = client_provider
        self._library = library or PromptLibrary()
        self._timeout_provider = timeout_provider or (lambda: 8.0)

    def __call__(self, text: str, step: ProcessingStep) -> str:
        """Возвращает ответ модели без изменений: проверять будет guard."""
        if not step.prompt_id:
            raise LlmError(f"Для шага «{step.id}» не задана инструкция")

        client = self._client_provider()
        if client is None:
            raise LlmError("сервер модели не подключён")

        try:
            system, user = self._library.render(step.prompt_id, text=text)
        except PromptError as exc:
            raise LlmError(str(exc)) from exc

        # Грубая оценка: одному символу русского текста хватает примерно
        # половины токена, берём запас на структурирование.
        max_tokens = max(MIN_MAX_TOKENS, len(text) * MAX_TOKENS_MULTIPLIER)

        answer = client.complete(
            system=system,
            user=user,
            temperature=0.0,
            max_tokens=max_tokens,
            timeout=self._timeout_provider(),
        )
        logger.debug(
            "Модель ответила: шаг %s, длина запроса %s, длина ответа %s",
            step.id,
            len(text),
            len(answer),
        )
        return answer
