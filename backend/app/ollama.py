from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator

import httpx


class OllamaUnavailableError(RuntimeError):
    """Raised when the local Ollama service or selected model is unavailable."""


def ollama_base_url() -> str:
    return os.getenv("COLA_OLLAMA_URL", "http://127.0.0.1:11434")


def ollama_model() -> str:
    return os.getenv("COLA_OLLAMA_MODEL", "llama3.2:3b")


async def available() -> bool:
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            response = await client.get(f"{ollama_base_url()}/api/tags")
            return response.is_success
    except httpx.HTTPError:
        return False


async def stream_answer(question: str) -> AsyncIterator[str]:
    payload = {
        "model": ollama_model(),
        "stream": True,
        "messages": [
            {
                "role": "system",
                "content": "Você é o Cola AI. Responda em português do Brasil, de forma objetiva, prática e confiável.",
            },
            {"role": "user", "content": question},
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=None) as client:
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
                    content = event.get("message", {}).get("content", "")
                    if content:
                        yield content
    except httpx.ConnectError as error:
        raise OllamaUnavailableError(
            "Ollama não está em execução. Instale-o e inicie o serviço local para usar a IA."
        ) from error
    except httpx.HTTPStatusError as error:
        raise OllamaUnavailableError(f"Falha ao consultar o Ollama: {error.response.status_code}") from error
