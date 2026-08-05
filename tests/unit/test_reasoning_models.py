"""Работа с моделями, которые сначала думают вслух.

Qwen3 по умолчанию выдаёт блок рассуждений. На правке одной фразы весь
отведённый запас токенов уходил в размышления, поле ответа оставалось пустым,
и обработка молча откатывалась к очистке правилами: перевод и режим
«Инструкция» просто не работали.
"""

from __future__ import annotations

import httpx
import pytest

from voiceflow.core.llm.base import LlmError
from voiceflow.core.llm.openai_compat import OpenAiCompatibleClient, _extract_text


def _response(payload: dict) -> httpx.Response:
    return httpx.Response(200, json=payload, request=httpx.Request("POST", "http://127.0.0.1"))


def test_request_turns_thinking_off() -> None:
    """Без этого параметра модель тратит весь ответ на размышления."""
    sent: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        sent.update(json.loads(request.content))
        return _response(
            {"choices": [{"message": {"content": "готовый текст"}, "finish_reason": "stop"}]}
        )

    client = OpenAiCompatibleClient("http://127.0.0.1:8079")
    client._client = httpx.Client(transport=httpx.MockTransport(handler))

    assert client.complete("система", "текст") == "готовый текст"
    assert sent["chat_template_kwargs"] == {"enable_thinking": False}


def test_answer_is_returned_as_is() -> None:
    text = _extract_text(
        _response({"choices": [{"message": {"content": "Нужно добавить кнопку."}}]})
    )

    assert text == "Нужно добавить кнопку."


def test_reasoning_without_answer_is_named_plainly() -> None:
    """Раньше это выглядело как «модель не ответила» — причина терялась."""
    payload = {
        "choices": [
            {
                "message": {"content": "", "reasoning_content": "думаю, что тут имелось в виду…"},
                "finish_reason": "length",
            }
        ]
    }

    with pytest.raises(LlmError, match="размышления"):
        _extract_text(_response(payload))


def test_truncated_answer_is_named_plainly() -> None:
    payload = {"choices": [{"message": {"content": "   "}, "finish_reason": "length"}]}

    with pytest.raises(LlmError, match="длину"):
        _extract_text(_response(payload))


def test_empty_answer_without_reason_is_allowed() -> None:
    """Пустой ответ на пустой ввод — не ошибка, дальше решает guard."""
    payload = {"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]}

    assert _extract_text(_response(payload)) == ""


def test_missing_choices_is_an_error() -> None:
    with pytest.raises(LlmError, match="вариантов"):
        _extract_text(_response({"choices": []}))


def test_timeout_default_allows_slow_machines() -> None:
    """Восьми секунд не хватало на процессоре, и обработка откатывалась."""
    from voiceflow.core.settings.schema import LlmSettings

    assert LlmSettings().timeout_s >= 15.0


def test_factory_settings_agree_with_the_schema() -> None:
    """Заводской файл перекрывает значения схемы, и они разъезжались."""
    import tomllib

    from voiceflow import paths
    from voiceflow.core.settings.schema import LlmSettings

    data = tomllib.loads((paths.config_dir() / "default_settings.toml").read_text("utf-8"))

    assert data["llm"]["timeout_s"] == LlmSettings().timeout_s
