import asyncio
import csv
import json
import sqlite3

import pytest

from backend.app import answer_provider
from backend.app.provider_errors import AnswerProviderError
from backend.app.question_bank import QuestionBank, build_bank, normalize


@pytest.fixture
def bank(tmp_path):
    source = tmp_path / "questions.csv"
    with source.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file, delimiter=";")
        writer.writerow(["Categoria", "Tema", "Tipo", "Pergunta"])
        writer.writerow(["Técnica", "cache", "Técnica", "Como analisar riscos de cache em produção?"])
        writer.writerow(["RH", "conflito", "RH", "Como avaliar um conflito com colegas?"])
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps([{
        "category": "Técnica", "theme": "EF Core", "questions": ["Quando usar AsNoTracking no EF Core?"],
        "answer": "Para leitura sem rastreamento."
    }]), encoding="utf-8")
    path = tmp_path / "bank.sqlite"
    assert build_bank(source, path, answers) == {"imported_questions": 2, "prepared_answers": 1}
    return QuestionBank(path)


def test_exact_accent_case_and_distinct_languages(bank):
    assert bank.lookup("QUANDO usar AsNoTracking no EF Core!").ready
    assert bank.lookup("No EF Core, quando usar AsNoTracking?").ready
    assert not bank.lookup("Como analisar riscos de cache em produção?").ready
    assert normalize("C#") != normalize("C++") != normalize("C")
    assert bank.lookup("Quando não usar AsNoTracking no EF Core?") is None
    assert bank.lookup("Quando usar AsNoTracking no Java?") is None
    assert bank.lookup("Receita de bolo de chocolate") is None
    assert "situação verdadeira" in bank.lookup("Como avaliar um conflito com colegas?").answer


def test_reimport_failure_preserves_existing_database(bank, tmp_path):
    invalid = tmp_path / "invalid.csv"
    invalid.write_text("bad;columns\n", encoding="utf-8")
    with pytest.raises(ValueError):
        build_bank(invalid, bank.path)
    assert bank.lookup("Quando usar AsNoTracking no EF Core?").ready


def test_conflicting_exact_answers_are_not_chosen_arbitrarily(bank):
    db = sqlite3.connect(bank.path)
    try:
        db.execute("INSERT INTO questions(question,normalized,category,theme,answer,ready) VALUES (?,?,?,?,?,1)",
                   ("Quando usar AsNoTracking no EF Core?", normalize("Quando usar AsNoTracking no EF Core?"), "Técnica", "EF Core", "Resposta conflitante"))
        db.commit()
    finally:
        db.close()
    assert bank.lookup("Quando usar AsNoTracking no EF Core?") is None


def collect(question, provisional=False):
    async def run():
        return "".join([part async for part in answer_provider.stream_answer(question, provisional=provisional)])
    return asyncio.run(run())


def test_ready_answer_works_without_ai(bank, monkeypatch):
    monkeypatch.setattr(answer_provider, "get_bank", lambda: bank)
    monkeypatch.setenv("COLA_LLM_PROVIDER", "openai")
    async def forbidden(*args, **kwargs):
        pytest.fail("Prepared answers must not call the provider")
        yield ""
    monkeypatch.setattr(answer_provider.openai_provider, "stream_answer", forbidden)
    assert "base local" in collect("Quando usar AsNoTracking no EF Core?")


def test_failure_returns_labeled_guide_and_does_not_invent_unknown_answer(bank, monkeypatch):
    monkeypatch.setattr(answer_provider, "get_bank", lambda: bank)
    monkeypatch.setenv("COLA_LLM_PROVIDER", "ollama")
    async def failed(*args, **kwargs):
        raise AnswerProviderError("unavailable")
        yield ""
    monkeypatch.setattr(answer_provider.ollama, "stream_answer", failed)
    answer = collect("Como analisar riscos de cache em produção?")
    assert "IA indisponível" in answer and "Roteiro local" in answer
    with pytest.raises(AnswerProviderError):
        collect("Uma pergunta totalmente desconhecida?")


def test_partial_provider_failure_does_not_mix_answers(bank, monkeypatch):
    monkeypatch.setattr(answer_provider, "get_bank", lambda: bank)
    monkeypatch.setenv("COLA_LLM_PROVIDER", "ollama")
    async def failed(*args, **kwargs):
        yield "Parcial da IA"
        raise AnswerProviderError("unavailable")
    monkeypatch.setattr(answer_provider.ollama, "stream_answer", failed)
    async def run():
        parts = []
        with pytest.raises(AnswerProviderError):
            async for part in answer_provider.stream_answer("Como analisar riscos de cache em produção?"):
                parts.append(part)
        assert parts == ["Parcial da IA"]
    asyncio.run(run())


def test_offline_unknown_and_provisional_are_conservative(bank, monkeypatch):
    monkeypatch.setattr(answer_provider, "get_bank", lambda: bank)
    monkeypatch.setenv("COLA_LLM_PROVIDER", "offline")
    assert "Não encontrei" in collect("Nada conhecido")
    assert collect("Quando usar AsNoTracking no EF Core?", provisional=True) == ""


def test_ai_receives_reference_as_data(bank, monkeypatch):
    monkeypatch.setattr(answer_provider, "get_bank", lambda: bank)
    monkeypatch.setenv("COLA_LLM_PROVIDER", "ollama")
    async def stream(question, *, provisional):
        payload = json.loads(question)
        assert payload["pergunta_atual"] == "Como analisar riscos de cache em produção?"
        assert "não é gabarito" in payload["referencia_local"]["tipo"]
        yield "Resposta adaptada"
    monkeypatch.setattr(answer_provider.ollama, "stream_answer", stream)
    assert collect("Como analisar riscos de cache em produção?") == "Resposta adaptada"
