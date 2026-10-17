import asyncio
import json

import pytest

from scripts.evaluate_technical import DEFAULT_CASES, TechnicalCase, evaluate_case, load_cases


def test_bank_selects_exact_cases_and_rejects_typos(tmp_path):
    assert len(load_cases(DEFAULT_CASES)) == 12
    assert [case.name for case in load_cases(DEFAULT_CASES, ["ef_tracking"])] == ["ef_tracking"]
    with pytest.raises(ValueError, match="desconhecidos"):
        load_cases(DEFAULT_CASES, ["typo"])
    duplicate = tmp_path / "cases.json"
    case = load_cases(DEFAULT_CASES)[0].model_dump()
    duplicate.write_text(json.dumps([case, case]), encoding="utf-8")
    with pytest.raises(ValueError, match="únicos"):
        load_cases(duplicate)


def test_stream_completion_does_not_claim_technical_correctness():
    async def stream(question):
        yield "Uma resposta "
        yield "possivelmente errada."
    case = TechnicalCase(name="case", question="Pergunta?", expected_behavior="Revisar.")
    result = asyncio.run(evaluate_case(case, stream, 1))
    assert result.status == "completed"
    assert result.quality_review == "pending"
    assert result.answer == "Uma resposta possivelmente errada."
    assert 0 <= result.first_delta_seconds <= result.total_seconds


def test_timeout_preserves_partial_output():
    async def stream(question):
        yield "Parcial"
        await asyncio.sleep(1)
    case = load_cases(DEFAULT_CASES)[0]
    result = asyncio.run(evaluate_case(case, stream, 0.01))
    assert result.status == "error"
    assert result.answer == "Parcial"
    assert result.quality_review == "not_evaluated"


def test_empty_output_and_exception_are_failures_without_leaking_secrets():
    async def empty(question):
        yield ""
    async def failed(question):
        raise RuntimeError("SECRET_TOKEN")
        yield ""  # marks this stub as an async generator
    case = load_cases(DEFAULT_CASES)[0]
    for stream in (empty, failed):
        result = asyncio.run(evaluate_case(case, stream, 1))
        assert result.status == "error"
        assert "SECRET_TOKEN" not in result.model_dump_json()
