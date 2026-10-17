"""Free-only OpenRouter streaming with a local request gate."""
from __future__ import annotations

import json
import os
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from .provider_errors import AnswerProviderError
from .technical_assistant import answer_system_prompt

URL = "https://openrouter.ai/api/v1/chat/completions"
_next_request = 0.0


def api_key() -> str:
    return os.getenv("OPENROUTER_API_KEY", "").strip()


def model_name() -> str:
    model = os.getenv("COLA_OPENROUTER_MODEL", "xingchen-agi/xing4.0-29b-a4b:free").strip()
    if model != "openrouter/free" and not model.endswith(":free"):
        raise AnswerProviderError("OpenRouter bloqueado: selecione um modelo :free ou openrouter/free.")
    return model


def model_names() -> list[str]:
    models = [model_name()]
    fallback = os.getenv("COLA_OPENROUTER_FALLBACK_MODELS", "nvidia/nemotron-3.5-super-vl:free")
    for model in fallback.split(","):
        model = model.strip()
        if not model:
            continue
        if model != "openrouter/free" and not model.endswith(":free"):
            raise AnswerProviderError("OpenRouter bloqueado: todos os modelos alternativos devem ser gratuitos.")
        if model not in models:
            models.append(model)
    return models


def defer_requests(seconds: float) -> None:
    global _next_request
    _next_request = max(_next_request, time.monotonic() + seconds)


def retry_delay(value: str | None) -> float:
    try:
        return max(60.0, float(value or "60"))
    except ValueError:
        try:
            return max(60.0, (parsedate_to_datetime(value or "") - datetime.now(UTC)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return 60.0


async def stream_answer(question: str, *, provisional: bool = False) -> AsyncIterator[str]:
    models = model_names()
    key = api_key()
    if not key:
        raise AnswerProviderError("Configure OPENROUTER_API_KEY no .env para habilitar a API gratuita.")
    if time.monotonic() < _next_request:
        raise AnswerProviderError("OpenRouter em intervalo de espera; usando alternativa local.")
    # Reserve before the first await: concurrent sessions cannot burst requests.
    defer_requests(4)
    payload = {
        "stream": True, "max_tokens": 300 if provisional else 1200,
        "provider": {"max_price": {"prompt": 0, "completion": 0, "request": 0}, "allow_fallbacks": True},
        "messages": [
            {"role": "system", "content": answer_system_prompt(provisional)},
            {"role": "user", "content": question},
        ],
    }
    if len(models) == 1:
        payload["model"] = models[0]
    else:
        payload["models"] = models
    received = False
    finished = False
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5)) as client:
            async with client.stream("POST", URL, headers={"Authorization": f"Bearer {key}"}, json=payload) as response:
                if response.is_error:
                    defer_requests(retry_delay(response.headers.get("Retry-After")) if response.status_code == 429 else 300)
                    raise AnswerProviderError(f"OpenRouter indisponível (HTTP {response.status_code}).")
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        finished = True
                        break
                    event = json.loads(data)
                    if event.get("error"):
                        defer_requests(60)
                        raise AnswerProviderError("OpenRouter interrompeu a geração.")
                    if not event.get("choices"):
                        continue
                    choice = event["choices"][0]
                    content = (choice.get("delta") or {}).get("content")
                    if content:
                        if not isinstance(content, str):
                            raise ValueError("invalid content")
                        received = True
                        yield content
                    if choice.get("finish_reason") == "length":
                        raise AnswerProviderError("OpenRouter atingiu o limite; a resposta está incompleta.")
                    if choice.get("finish_reason") == "error":
                        raise AnswerProviderError("OpenRouter interrompeu a geração.")
                    if choice.get("finish_reason") == "stop":
                        finished = True
        if not received or not finished:
            raise AnswerProviderError("OpenRouter não concluiu uma resposta válida.")
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
        defer_requests(60)
        raise AnswerProviderError("Falha de conexão ou resposta inválida do OpenRouter.") from error
