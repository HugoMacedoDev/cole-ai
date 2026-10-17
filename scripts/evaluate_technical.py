"""Explicit live evaluation; never runs network calls as part of pytest."""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "tests" / "technical_cases.json"
AnswerStream = Callable[[str], AsyncIterator[str]]


class TechnicalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    question: str = Field(min_length=1)
    expected_behavior: str = Field(min_length=1)
    sources: list[str] = Field(default_factory=list)


class CaseResult(BaseModel):
    case: TechnicalCase
    status: Literal["completed", "error"]
    answer: str
    first_delta_seconds: float | None
    total_seconds: float
    error: str | None = None
    quality_review: Literal["pending", "not_evaluated"]


def load_cases(path: Path, selected: list[str] | None = None) -> list[TechnicalCase]:
    cases = TypeAdapter(list[TechnicalCase]).validate_json(path.read_text(encoding="utf-8"))
    names = [case.name for case in cases]
    if not cases or len(names) != len(set(names)):
        raise ValueError("O banco deve conter casos com nomes únicos.")
    if selected:
        unknown = set(selected) - set(names)
        if unknown:
            raise ValueError(f"Casos desconhecidos: {', '.join(sorted(unknown))}")
        cases = [case for case in cases if case.name in selected]
    return cases


async def evaluate_case(case: TechnicalCase, stream: AnswerStream, timeout: float) -> CaseResult:
    started = time.monotonic()
    first_delta = None
    parts: list[str] = []
    error = None
    try:
        async with asyncio.timeout(timeout):
            async for part in stream(case.question):
                if not part:
                    continue
                if first_delta is None:
                    first_delta = time.monotonic() - started
                parts.append(part)
            if not "".join(parts).strip():
                raise ValueError("O modelo não produziu uma resposta.")
    except TimeoutError:
        error = "Tempo limite excedido."
    except Exception as exc:
        # Do not persist arbitrary exception text, request headers or credentials.
        error = f"Falha na geração ({type(exc).__name__})."
    return CaseResult(
        case=case, status="error" if error else "completed", answer="".join(parts),
        first_delta_seconds=first_delta, total_seconds=time.monotonic() - started,
        error=error, quality_review="not_evaluated" if error else "pending",
    )


async def run(args: argparse.Namespace) -> int:
    cases = load_cases(args.cases, args.case)
    if args.provider == "ollama":
        from backend.app.ollama import ollama_model, stream_answer
        model = ollama_model()
    else:
        from backend.app.openai_provider import openai_model, stream_answer
        model = openai_model()
    results: list[CaseResult] = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for case in cases:
        result = await evaluate_case(case, stream_answer, args.timeout)
        results.append(result)
        report = {
            "provider": args.provider, "model": model,
            "scope": "Texto direto ao provedor; não valida áudio ou interface. Qualidade requer revisão humana.",
            "results": [item.model_dump() for item in results],
        }
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{case.name}: {result.status}; first={result.first_delta_seconds}; total={result.total_seconds:.2f}s", flush=True)
    return int(any(result.status == "error" for result in results))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("ollama", "openai"), required=True)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--case", action="append", help="Nome do caso; pode repetir. Sem filtro, executa todos.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=90)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout deve ser positivo")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
