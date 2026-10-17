import asyncio
import json

import httpx
import pytest

from backend.app import answer_provider, openrouter_provider
from backend.app.provider_errors import AnswerProviderError


@pytest.fixture(autouse=True)
def config(monkeypatch):
    monkeypatch.setattr(openrouter_provider, "_next_request", 0)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("COLA_OPENROUTER_MODEL", "test/model:free")
    monkeypatch.setenv("COLA_OPENROUTER_FALLBACK_MODELS", "")
    monkeypatch.setenv("COLA_FREE_ONLY", "true")
    monkeypatch.setenv("COLA_LLM_PROVIDER", "auto")


def install(monkeypatch, handler):
    client = httpx.AsyncClient
    monkeypatch.setattr(openrouter_provider.httpx, "AsyncClient", lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs))


def collect(stream):
    async def run():
        return [part async for part in stream]
    return asyncio.run(run())


def test_stream_enforces_zero_prices_and_ignores_heartbeats(monkeypatch):
    def handler(request):
        assert request.headers["Authorization"] == "Bearer test-key"
        data = json.loads(request.content)
        assert data["model"].endswith(":free")
        assert data["provider"]["max_price"] == {"prompt": 0, "completion": 0, "request": 0}
        assert "plugins" not in data
        return httpx.Response(200, text=': heartbeat\n\ndata: {"choices":[{"delta":{"content":"Resposta"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
    install(monkeypatch, handler)
    assert collect(openrouter_provider.stream_answer("Pergunta")) == ["Resposta"]


def test_paid_model_rejected_before_request(monkeypatch):
    monkeypatch.setenv("COLA_OPENROUTER_MODEL", "openai/paid")
    install(monkeypatch, lambda request: pytest.fail("Paid model must not be requested"))
    with pytest.raises(AnswerProviderError, match="bloqueado"):
        collect(openrouter_provider.stream_answer("Pergunta"))


def test_requested_models_are_sent_in_order_with_zero_price(monkeypatch):
    primary = "xingchen-agi/xing4.0-29b-a4b:free"
    fallback = "nvidia/nemotron-3.5-super-vl:free"
    monkeypatch.setenv("COLA_OPENROUTER_MODEL", primary)
    monkeypatch.setenv("COLA_OPENROUTER_FALLBACK_MODELS", f" {fallback}, {primary}, {fallback}")
    def handler(request):
        payload = json.loads(request.content)
        assert payload["models"] == [primary, fallback]
        assert "model" not in payload
        assert payload["provider"]["max_price"] == {"prompt": 0, "completion": 0, "request": 0}
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"OK"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n')
    install(monkeypatch, handler)
    assert collect(openrouter_provider.stream_answer("Pergunta")) == ["OK"]


def test_paid_fallback_rejected_before_request(monkeypatch):
    monkeypatch.setenv("COLA_OPENROUTER_FALLBACK_MODELS", "nvidia/nemotron-3.5-super-vl")
    install(monkeypatch, lambda request: pytest.fail("Paid fallback must not be requested"))
    with pytest.raises(AnswerProviderError, match="gratuitos"):
        collect(openrouter_provider.stream_answer("Pergunta"))


def test_missing_key_does_not_send_request(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    install(monkeypatch, lambda request: pytest.fail("Missing key must not send HTTP"))
    with pytest.raises(AnswerProviderError, match="OPENROUTER_API_KEY"):
        collect(openrouter_provider.stream_answer("Pergunta"))


def test_rate_limit_cooldown_does_not_repeat_http_calls(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "120"})
    install(monkeypatch, handler)
    for _ in range(2):
        with pytest.raises(AnswerProviderError):
            collect(openrouter_provider.stream_answer("Pergunta"))
    assert len(calls) == 1
    assert openrouter_provider._next_request - openrouter_provider.time.monotonic() > 110


@pytest.mark.parametrize("body", [
    'data: {"error":{"message":"failed"}}\n',
    'data: {"choices":[{"delta":{"content":"partial"}}]}\n',
    'data: [DONE]\n',
    'data: invalid\n',
])
def test_invalid_or_truncated_stream_is_failure(monkeypatch, body):
    install(monkeypatch, lambda request: httpx.Response(200, text=body))
    with pytest.raises(AnswerProviderError):
        collect(openrouter_provider.stream_answer("Pergunta"))


def test_free_mode_never_selects_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "present")
    monkeypatch.setenv("COLA_LLM_PROVIDER", "openai")
    assert answer_provider.provider_name() == "openrouter"
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    assert answer_provider.provider_name() == "ollama"


def test_cloud_failure_falls_back_and_partials_stay_local(monkeypatch):
    calls = []
    async def cloud(*args, **kwargs):
        calls.append("cloud")
        raise AnswerProviderError("429")
        yield ""
    async def local(*args, **kwargs):
        calls.append("local")
        yield "Local"
    monkeypatch.setattr(openrouter_provider, "stream_answer", cloud)
    monkeypatch.setattr(answer_provider.ollama, "stream_answer", local)
    assert collect(answer_provider.routed_answer("Pergunta", provisional=False)) == ["Local"]
    assert calls == ["cloud", "local"]
    calls.clear()
    assert collect(answer_provider.routed_answer("Pergunta", provisional=True)) == ["Local"]
    assert calls == ["local"]


def test_never_mix_partial_cloud_output_with_another_provider(monkeypatch):
    async def cloud(*args, **kwargs):
        yield "Partial"
        raise AnswerProviderError("broken")
    async def local(*args, **kwargs):
        pytest.fail("Must preserve partial text without replacement")
        yield ""
    monkeypatch.setattr(openrouter_provider, "stream_answer", cloud)
    monkeypatch.setattr(answer_provider.ollama, "stream_answer", local)
    with pytest.raises(AnswerProviderError):
        collect(answer_provider.routed_answer("Pergunta", provisional=False))


def test_timeout_falls_back_and_closes_cloud_generator(monkeypatch):
    closed = []
    original_wait = asyncio.wait_for
    async def short_wait(awaitable, timeout):
        return await original_wait(awaitable, timeout=0.01)
    async def cloud(*args, **kwargs):
        try:
            await asyncio.sleep(10)
            yield "late"
        finally:
            closed.append(True)
    async def local(*args, **kwargs):
        yield "Local"
    monkeypatch.setattr(answer_provider.asyncio, "wait_for", short_wait)
    monkeypatch.setattr(openrouter_provider, "stream_answer", cloud)
    monkeypatch.setattr(answer_provider.ollama, "stream_answer", local)
    assert collect(answer_provider.routed_answer("Pergunta", provisional=False)) == ["Local"]
    assert closed == [True]
