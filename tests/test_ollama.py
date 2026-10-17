import asyncio
import json

import httpx
import pytest

from backend.app import ollama


def test_stream_preserves_question_and_uses_stable_generation(monkeypatch):
    question = "Como indexar clientes por email? Banana azul. No PostgreSQL."
    real_client = httpx.AsyncClient
    calls = []

    def handler(request):
        calls.append(request)
        payload = json.loads(request.content)
        assert payload["messages"][-1] == {"role": "user", "content": question}
        if "format" in payload:
            return httpx.Response(200, json={"message": {"content": json.dumps({"clear": True, "question": question, "clarification": ""})}})
        assert payload["options"]["temperature"] == 0
        assert payload["options"]["num_predict"] == 1200
        assert payload["think"] is False
        assert payload["model"] == "test-model"
        return httpx.Response(200, text='{"message":{"content":"CREATE "}}\n{"message":{"content":"INDEX"}}\n{"done":true}\n')

    monkeypatch.setenv("COLA_OLLAMA_MODEL", "test-model")
    monkeypatch.setattr(ollama.httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))

    async def scenario():
        return "".join([part async for part in ollama.stream_answer(question)])

    assert asyncio.run(scenario()) == "CREATE INDEX"
    assert len(calls) == 1


@pytest.mark.parametrize("status,body", [
    (404, ""), (200, '{"error":"model failed"}\n'), (200, "invalid json\n"),
    (200, '{"message":{"thinking":"internal"},"done":true}\n'),
    (200, '{"done":true,"done_reason":"length"}\n'),
])
def test_provider_failure_is_not_replaced_with_invented_answer(monkeypatch, status, body):
    real_client = httpx.AsyncClient
    def handler(request):
        if "format" in json.loads(request.content):
            return httpx.Response(200, json={"message": {"content": json.dumps({"clear": True, "question": "Pergunta", "clarification": ""})}})
        return httpx.Response(status, text=body)
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(ollama.httpx, "AsyncClient", lambda **kwargs: real_client(transport=transport, **kwargs))

    async def scenario():
        return [part async for part in ollama.stream_answer("Pergunta")]

    with pytest.raises(ollama.OllamaUnavailableError):
        asyncio.run(scenario())


def test_complete_question_streams_clarification_in_one_call(monkeypatch):
    real_client = httpx.AsyncClient
    calls = []

    def handler(request):
        calls.append(request)
        payload = json.loads(request.content)
        assert "format" not in payload
        assert "esclarecimento" in payload["messages"][0]["content"]
        return httpx.Response(200, text=json.dumps({"message": {"content": "Qual banco de dados você usa?"}}) + "\n")

    monkeypatch.setattr(ollama.httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))

    async def scenario():
        return "".join([part async for part in ollama.stream_answer("fala ilegível")])

    assert asyncio.run(scenario()) == "Qual banco de dados você usa?"
    assert len(calls) == 1


def test_unclear_partial_waits_for_more_speech(monkeypatch):
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"message": {"content": json.dumps({
        "clear": False, "question": "", "clarification": "Qual banco?"
    })}}))
    monkeypatch.setattr(ollama.httpx, "AsyncClient", lambda **kwargs: real_client(transport=transport, **kwargs))

    async def scenario():
        return [part async for part in ollama.stream_answer("Como fazer...", provisional=True)]

    assert asyncio.run(scenario()) == []
