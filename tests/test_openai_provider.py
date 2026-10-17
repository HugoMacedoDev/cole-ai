import asyncio
import json

import httpx
import pytest

from backend.app import answer_provider, openai_provider
from backend.app.technical_assistant import SYSTEM_PROMPT

INTENT_OK = {"clear": True, "question": "Processo vs thread?", "clarification": ""}


def _intent_response(intent: dict) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(intent)}}]})


def _sse(*chunks: dict) -> str:
    return "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"


def _delta(text: str, finish: str | None = None) -> dict:
    return {"choices": [{"delta": {"content": text}, "finish_reason": finish}]}


def _install(monkeypatch, handler) -> None:
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        openai_provider.httpx, "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )


def _collect(question: str, provisional: bool = False) -> list[str]:
    async def scenario():
        return [part async for part in openai_provider.stream_answer(question, provisional=provisional)]
    return asyncio.run(scenario())


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("COLA_OPENAI_MODEL", "test-model")


def test_streams_answer_with_interview_prompt_and_auth(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer test-key"
        payload = json.loads(request.content)
        assert payload["model"] == "test-model"
        if "response_format" in payload:
            assert payload["response_format"]["json_schema"]["strict"] is True
            return _intent_response(INTENT_OK)
        assert payload["stream"] is True
        assert payload["messages"][0]["content"] == SYSTEM_PROMPT
        assert payload["messages"][-1]["content"] == "processo vs thread banana"
        return httpx.Response(200, text=_sse(_delta("Na prática, "), _delta("eu uso thread.", "stop")))

    _install(monkeypatch, handler)
    assert "".join(_collect("processo vs thread banana")) == "Na prática, eu uso thread."
    assert len(calls) == 1


def test_complete_question_streams_clarification_in_one_call(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        payload = json.loads(request.content)
        assert "response_format" not in payload
        assert "esclarecimento" in payload["messages"][0]["content"]
        return httpx.Response(200, text=_sse(_delta("Qual banco?", "stop")))

    _install(monkeypatch, handler)
    assert _collect("fala ilegível") == ["Qual banco?"]
    assert len(calls) == 1


def test_unclear_partial_waits_for_more_speech(monkeypatch):
    _install(monkeypatch, lambda request: _intent_response({"clear": False, "question": "", "clarification": "?"}))
    assert _collect("Como fazer...", provisional=True) == []


def test_missing_key_raises_clear_error(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    _install(monkeypatch, lambda request: pytest.fail("no request expected"))
    with pytest.raises(openai_provider.OpenAIUnavailableError, match="OPENAI_API_KEY"):
        _collect("Pergunta")


def test_empty_temperature_is_omitted(monkeypatch):
    monkeypatch.setenv("COLA_OPENAI_TEMPERATURE", "")

    def handler(request):
        payload = json.loads(request.content)
        if "response_format" in payload:
            return _intent_response(INTENT_OK)
        assert "temperature" not in payload
        return httpx.Response(200, text=_sse(_delta("ok", "stop")))

    _install(monkeypatch, handler)
    assert _collect("Pergunta") == ["ok"]


@pytest.mark.parametrize("status,body", [
    (401, ""), (429, ""), (500, ""),
    (200, _sse({"choices": [{"delta": {}, "finish_reason": "stop"}]})),
    (200, _sse(_delta("parcial", "length"))),
    (200, "data: invalid json\n\n"),
])
def test_failures_raise_instead_of_inventing_answer(monkeypatch, status, body):
    def handler(request):
        if "response_format" in json.loads(request.content):
            return _intent_response(INTENT_OK)
        return httpx.Response(status, text=body)

    _install(monkeypatch, handler)
    with pytest.raises(openai_provider.OpenAIUnavailableError):
        _collect("Pergunta")


@pytest.mark.parametrize("configured,key,expected", [
    ("auto", "k", "openai"), ("auto", "", "ollama"),
    ("ollama", "k", "ollama"), ("openai", "", "openai"),
])
def test_provider_selection(monkeypatch, configured, key, expected):
    monkeypatch.setenv("COLA_FREE_ONLY", "false")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("COLA_LLM_PROVIDER", configured)
    monkeypatch.setenv("OPENAI_API_KEY", key)
    assert answer_provider.provider_name() == expected
