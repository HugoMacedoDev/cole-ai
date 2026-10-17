"""OpenAI Chat Completions answer provider (streaming, via HTTPX)."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .provider_errors import AnswerProviderError
from .technical_assistant import INTENT_PROMPT, QuestionIntent, answer_system_prompt

# Strict structured-output schema mirroring QuestionIntent; Pydantic still validates limits.
INTENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "clear": {"type": "boolean"},
        "question": {"type": "string"},
        "clarification": {"type": "string"},
    },
    "required": ["clear", "question", "clarification"],
    "additionalProperties": False,
}


class OpenAIUnavailableError(AnswerProviderError):
    """Raised when the OpenAI API is unconfigured, unreachable or rejects the request."""


def openai_api_key() -> str:
    return os.getenv("OPENAI_API_KEY", "").strip()


def openai_base_url() -> str:
    return os.getenv("COLA_OPENAI_URL", "https://api.openai.com/v1").rstrip("/")


def openai_model() -> str:
    return os.getenv("COLA_OPENAI_MODEL", "gpt-4o-mini")


def openai_temperature() -> float | None:
    """Empty value omits temperature, for models that reject the parameter."""
    raw = os.getenv("COLA_OPENAI_TEMPERATURE", "0.4").strip()
    return float(raw) if raw else None


def _headers() -> dict[str, str]:
    key = openai_api_key()
    if not key:
        raise OpenAIUnavailableError("OPENAI_API_KEY não configurada. Defina a chave no arquivo .env.")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _base_payload(messages: list[dict[str, str]], max_tokens: int) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": openai_model(),
        "messages": messages,
        "max_completion_tokens": max_tokens,
    }
    temperature = openai_temperature()
    if temperature is not None:
        payload["temperature"] = temperature
    return payload


def _status_error(status: int) -> OpenAIUnavailableError:
    messages = {
        401: "Chave da OpenAI inválida. Verifique OPENAI_API_KEY.",
        403: "A chave da OpenAI não tem permissão para este modelo.",
        404: f"Modelo OpenAI '{openai_model()}' não encontrado. Ajuste COLA_OPENAI_MODEL.",
        429: "Limite de uso ou créditos da OpenAI esgotados. Tente novamente mais tarde.",
    }
    return OpenAIUnavailableError(messages.get(status, f"Falha ao consultar a OpenAI: {status}"))


async def interpret_question(client: httpx.AsyncClient, question: str) -> QuestionIntent:
    payload = _base_payload(
        [{"role": "system", "content": INTENT_PROMPT}, {"role": "user", "content": question}],
        max_tokens=512,
    )
    payload["temperature"] = 0
    payload["response_format"] = {
        "type": "json_schema",
        "json_schema": {"name": "question_intent", "strict": True, "schema": INTENT_SCHEMA},
    }
    response = await client.post(f"{openai_base_url()}/chat/completions", headers=_headers(), json=payload)
    if response.is_error:
        raise _status_error(response.status_code)
    content = response.json()["choices"][0]["message"]["content"]
    return QuestionIntent.model_validate_json(content)


def _parse_sse_line(line: str) -> dict[str, Any] | None:
    """Return the JSON chunk of an SSE data line, or None for keep-alives and [DONE]."""
    if not line.startswith("data:"):
        return None
    data = line[len("data:"):].strip()
    if not data or data == "[DONE]":
        return None
    return json.loads(data)


async def stream_answer(question: str, *, provisional: bool = False) -> AsyncIterator[str]:
    received_answer = False
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=5)) as client:
            if provisional:
                intent = await interpret_question(client, question)
                if not intent.clear:
                    return
                if not intent.question.strip():
                    raise OpenAIUnavailableError("Não consegui identificar a pergunta. Pode repeti-la?")
                question = intent.question
            payload = _base_payload(
                [
                    {"role": "system", "content": answer_system_prompt(provisional)},
                    {"role": "user", "content": question},
                ],
                max_tokens=300 if provisional else 1200,
            )
            payload["stream"] = True
            async with client.stream(
                "POST", f"{openai_base_url()}/chat/completions", headers=_headers(), json=payload
            ) as response:
                if response.is_error:
                    raise _status_error(response.status_code)
                async for line in response.aiter_lines():
                    chunk = _parse_sse_line(line)
                    if chunk is None or not chunk.get("choices"):
                        continue
                    choice = chunk["choices"][0]
                    content = (choice.get("delta") or {}).get("content") or ""
                    if content:
                        received_answer = True
                        yield content
                    if choice.get("finish_reason") == "length":
                        raise OpenAIUnavailableError(
                            "O modelo atingiu o limite de geração. A resposta pode estar incompleta."
                        )
        if not received_answer:
            raise OpenAIUnavailableError("O modelo não produziu uma resposta. Tente reformular a pergunta.")
    except httpx.ConnectError as error:
        raise OpenAIUnavailableError("Sem conexão com a API da OpenAI. Verifique sua internet.") from error
    except (httpx.HTTPError, ValueError, KeyError, IndexError) as error:
        raise OpenAIUnavailableError("A resposta da OpenAI falhou ou excedeu o tempo de espera. Tente novamente.") from error
