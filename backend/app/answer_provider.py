"""Selects the answer provider (Ollama or OpenAI) from the environment."""

from __future__ import annotations

import os
import asyncio
import json
import logging
import sqlite3
from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Literal

from . import ollama, openai_provider, openrouter_provider
from .provider_errors import AnswerProviderError
from .question_bank import BankMatch, get_bank

ProviderName = Literal["ollama", "openai", "openrouter", "offline"]
logger = logging.getLogger(__name__)


def provider_name() -> ProviderName:
    """Auto never chooses a paid service while free-only mode is enabled."""
    configured = os.getenv("COLA_LLM_PROVIDER", "auto").strip().lower()
    free_only = os.getenv("COLA_FREE_ONLY", "true").lower() != "false"
    if configured in ("ollama", "openrouter", "offline"):
        return configured  # type: ignore[return-value]
    if configured == "openai" and not free_only:
        return "openai"
    if openrouter_provider.api_key():
        return "openrouter"
    if not free_only and openai_provider.openai_api_key():
        return "openai"
    return "ollama"


async def routed_answer(question: str, *, provisional: bool) -> AsyncIterator[str]:
    # Continuous partials stay local; cloud quota is reserved for final questions.
    primary = "ollama" if provisional else provider_name()
    chain = [primary] if primary == "ollama" else [primary, "ollama"]
    last_error: AnswerProviderError | None = None
    for name in chain:
        stream = {"openai": openai_provider.stream_answer, "openrouter": openrouter_provider.stream_answer,
                  "ollama": ollama.stream_answer}[name]
        emitted = False
        try:
            async with aclosing(stream(question, provisional=provisional)) as iterator:
                if name != "ollama":
                    # Heartbeat SSE frames must not keep us waiting indefinitely.
                    first = await asyncio.wait_for(anext(iterator), timeout=12)
                    emitted = bool(first)
                    yield first
                async for part in iterator:
                    emitted = emitted or bool(part)
                    yield part
            return
        except StopAsyncIteration:
            last_error = AnswerProviderError("O provedor não produziu uma resposta.")
        except (AnswerProviderError, TimeoutError) as error:
            if emitted:
                raise AnswerProviderError("A geração foi interrompida. O texto parcial foi preservado.") from error
            last_error = error if isinstance(error, AnswerProviderError) else AnswerProviderError("Tempo de espera do provedor excedido.")
            if name == "openrouter" and isinstance(error, TimeoutError):
                openrouter_provider.defer_requests(60)
        logger.info("answer_provider_fallback provider=%s", name)
    raise last_error or AnswerProviderError("Nenhum provedor disponível.")


def lookup_question(question: str) -> BankMatch | None:
    try:
        bank = get_bank()
        return bank.lookup(question) if bank else None
    except (OSError, ValueError, sqlite3.Error):
        logger.warning("question_bank_unavailable")
        return None


async def stream_answer(question: str, *, provisional: bool = False) -> AsyncIterator[str]:
    match = await asyncio.to_thread(lookup_question, question)
    # Partial speech may still introduce a negation or important constraint.
    if match and match.ready and not provisional:
        yield match.offline_text()
        return
    if provider_name() == "offline":
        if not provisional:
            yield match.offline_text() if match else "[Base local] Não encontrei uma resposta confiável para esta pergunta. Informe o tema e reformule a pergunta."
        return
    prompt = question
    if match:
        prompt = json.dumps({"pergunta_atual": question, "referencia_local": {
            "categoria": match.category, "tema": match.theme,
            "tipo": "resposta preparada" if match.ready else "roteiro genérico, não é gabarito técnico",
            "conteudo": match.answer,
        }}, ensure_ascii=False)
    emitted = False
    try:
        async for part in routed_answer(prompt, provisional=provisional):
            emitted = emitted or bool(part)
            yield part
    except AnswerProviderError:
        # Never append a different canned answer to a partially generated one.
        if emitted or not match or provisional:
            raise
        yield "[IA indisponível]\n" + match.offline_text()
