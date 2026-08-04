"""Клиент локального сервера модели."""

from __future__ import annotations

import httpx
import pytest

from voiceflow.core.llm.base import LlmError, LlmRefusedError, LlmTimeoutError
from voiceflow.core.llm.llama_server import LlamaServer, ServerConfig
from voiceflow.core.llm.openai_compat import OpenAiCompatibleClient, is_loopback

# --------------------------------------------------------------------------- #
# Ограничение на локальный адрес
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://127.0.0.1:8079",
        "http://localhost:11434",
        "http://[::1]:8080",
        "http://127.5.0.1:1234",
    ],
)
def test_loopback_endpoints_are_allowed(endpoint: str) -> None:
    assert is_loopback(endpoint) is True
    OpenAiCompatibleClient(endpoint).close()


@pytest.mark.parametrize(
    "endpoint",
    ["http://example.com", "https://api.openai.com", "http://192.168.1.10:8080"],
)
def test_remote_endpoints_are_refused(endpoint: str) -> None:
    """Приложение обещает локальную работу — молча ходить наружу нельзя."""
    assert is_loopback(endpoint) is False
    with pytest.raises(LlmRefusedError, match="не является локальным"):
        OpenAiCompatibleClient(endpoint)


def test_remote_endpoint_can_be_allowed_explicitly() -> None:
    client = OpenAiCompatibleClient("http://192.168.1.10:8080", allow_remote=True)
    client.close()


# --------------------------------------------------------------------------- #
# Обращение к модели
# --------------------------------------------------------------------------- #


def make_client(handler) -> OpenAiCompatibleClient:  # type: ignore[no-untyped-def]
    client = OpenAiCompatibleClient("http://127.0.0.1:8079")
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    return client


def chat_response(text: str) -> httpx.Response:
    return httpx.Response(
        200, json={"choices": [{"message": {"role": "assistant", "content": text}}]}
    )


def test_completion_returns_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        return chat_response("готовый ответ")

    client = make_client(handler)

    assert client.complete("правила", "текст") == "готовый ответ"


def test_system_message_is_sent() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.append(json.loads(request.content))
        return chat_response("ответ")

    make_client(handler).complete("правила", "текст")

    messages = seen[0]["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "правила"
    assert messages[1]["content"] == "текст"


def test_empty_system_message_is_omitted() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.append(json.loads(request.content))
        return chat_response("ответ")

    make_client(handler).complete("   ", "текст")

    assert len(seen[0]["messages"]) == 1


def test_temperature_is_zero_by_default() -> None:
    """Обработка текста должна быть повторяемой."""
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.append(json.loads(request.content))
        return chat_response("ответ")

    make_client(handler).complete("", "текст")

    assert seen[0]["temperature"] == 0.0
    assert seen[0]["stream"] is False


def test_server_error_is_reported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="что-то сломалось")

    with pytest.raises(LlmError, match="500"):
        make_client(handler).complete("", "текст")


def test_timeout_is_reported_separately() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("слишком долго", request=request)

    with pytest.raises(LlmTimeoutError, match="не ответила"):
        make_client(handler).complete("", "текст")


def test_malformed_answer_is_reported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    with pytest.raises(LlmError, match="вариантов ответа"):
        make_client(handler).complete("", "текст")


def test_availability_check() -> None:
    def healthy(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"})

    def dead(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("нет соединения", request=request)

    assert make_client(healthy).is_available() is True
    assert make_client(dead).is_available() is False


def test_info_reflects_availability() -> None:
    def dead(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("нет соединения", request=request)

    info = make_client(dead).info()

    assert info.available is False
    assert info.endpoint == "http://127.0.0.1:8079"
    assert info.detail


# --------------------------------------------------------------------------- #
# Команда запуска сервера
# --------------------------------------------------------------------------- #


def test_server_command_contains_key_arguments(tmp_path) -> None:  # type: ignore[no-untyped-def]
    model = tmp_path / "model.gguf"
    model.write_bytes(b"")
    server = LlamaServer(
        ServerConfig(model_path=model, port=9000, n_gpu_layers=33, context_size=2048),
        executable=tmp_path / "llama-server.exe",
    )

    command = server.command()

    assert str(model) in command
    assert "--port" in command and "9000" in command
    assert "--n-gpu-layers" in command and "33" in command
    assert "--ctx-size" in command and "2048" in command
    # Сервер обязан слушать только петлевой адрес.
    assert "127.0.0.1" in command


def test_server_endpoint_is_loopback(tmp_path) -> None:  # type: ignore[no-untyped-def]
    server = LlamaServer(ServerConfig(model_path=tmp_path / "m.gguf", port=1234))

    assert server.endpoint == "http://127.0.0.1:1234"
    assert is_loopback(server.endpoint)
