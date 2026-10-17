from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator

import httpx

from .provider_errors import AnswerProviderError
from .technical_assistant import INTENT_PROMPT, QuestionIntent, answer_system_prompt


class OllamaUnavailableError(AnswerProviderError):
    """Raised when the local Ollama service or selected model is unavailable."""


def ollama_base_url() -> str:
    return os.getenv("COLA_OLLAMA_URL", "http://127.0.0.1:11434")


def ollama_model() -> str:
    return os.getenv("COLA_OLLAMA_MODEL", "qwen3.5:9b")


async def available() -> bool:
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            response = await client.get(f"{ollama_base_url()}/api/tags")
            return response.is_success
    except httpx.HTTPError:
        return False


async def interpret_question(client: httpx.AsyncClient, question: str) -> QuestionIntent:
    response = await client.post(f"{ollama_base_url()}/api/chat", json={
        "model": ollama_model(), "stream": False, "think": False,
        "format": QuestionIntent.model_json_schema(),
        "options": {"temperature": 0, "seed": 42, "num_ctx": 16384, "num_predict": 512},
        "messages": [
            {"role": "system", "content": INTENT_PROMPT},
            {"role": "user", "content": question},
        ],
    })
    response.raise_for_status()
    return QuestionIntent.model_validate_json(response.json()["message"]["content"])


async def stream_answer(question: str, *, provisional: bool = False) -> AsyncIterator[str]:
    payload = {
        "model": ollama_model(),
        "stream": True,
        "think": False,
        "options": {"temperature": 0, "seed": 42, "num_ctx": 16384, "num_predict": 640 if provisional else 1200},
        "messages": [
            {"role": "system", "content": answer_system_prompt(provisional)},
            {"role": "user", "content": question},
        ],
    }
    received_answer = False
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=5)) as client:
            # Incomplete speech still needs an intent gate. Complete questions
            # use the answer prompt to interpret and respond in one streamed call.
            if provisional:
                intent = await interpret_question(client, question)
                if not intent.clear:
                    return
                if not intent.question.strip():
                    raise OllamaUnavailableError("Não consegui identificar a pergunta. Pode repeti-la?")
                payload["messages"][-1]["content"] = intent.question
            async with client.stream("POST", f"{ollama_base_url()}/api/chat", json=payload) as response:
                if response.status_code == 404:
                    raise OllamaUnavailableError(
                        f"Modelo local '{ollama_model()}' não encontrado. Execute: ollama pull {ollama_model()}"
                    )
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    event = json.loads(line)
                    if event.get("error"):
                        raise OllamaUnavailableError(f"Ollama: {event['error']}")
                    content = event.get("message", {}).get("content", "")
                    if content:
                        received_answer = True
                        yield content
                    if event.get("done") and event.get("done_reason") == "length":
                        raise OllamaUnavailableError("O modelo atingiu o limite de geração. A resposta pode estar incompleta; tente uma pergunta mais específica.")
        if not received_answer:
            raise OllamaUnavailableError("O modelo não produziu uma resposta. Tente reformular a pergunta.")
    except httpx.ConnectError as error:
        raise OllamaUnavailableError(
            "Ollama não está em execução. Instale-o e inicie o serviço local para usar a IA."
        ) from error
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 404:
            raise OllamaUnavailableError(
                f"Modelo local '{ollama_model()}' não encontrado. Execute: ollama pull {ollama_model()}"
            ) from error
        raise OllamaUnavailableError(f"Falha ao consultar o Ollama: {error.response.status_code}") from error
    except (httpx.HTTPError, ValueError, KeyError) as error:
        raise OllamaUnavailableError("A resposta do Ollama falhou ou excedeu o tempo de espera. Tente novamente.") from error
