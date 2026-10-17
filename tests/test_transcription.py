import asyncio
import struct
import threading

import pytest
from backend.app.transcription import transcriber

from backend.app.session import Session, SessionManager
from backend.app.speech_pipeline import SpeechPipeline, Transcript
from backend.app.transcription import AudioChunk, SpeechSegmenter, SpeechSnapshot


def audio(seconds: float, amplitude: int = 1000) -> AudioChunk:
    return AudioChunk(struct.pack("<h", amplitude) * int(16000 * seconds), 16000, 1)


def test_segmenter_silence_boundary_and_reset():
    segmenter = SpeechSegmenter()
    assert segmenter.feed(audio(1, 0)) is None
    assert segmenter.feed(audio(1)) is None
    result = segmenter.feed(audio(0.9, 0))
    assert result is not None and result.audio.duration == 1.9 and result.final
    assert segmenter.feed(audio(1, 0)) is None


def test_repeated_partial_whitespace_is_coalesced_but_final_is_preserved():
    async def scenario():
        pipeline = SpeechPipeline(SessionManager(), Session("test", Socket()))
        try:
            pipeline._submit(Transcript("Como  funciona?", 0, False))
            pipeline._answer_ready.clear()
            pipeline._submit(Transcript(" Como funciona? ", 0, False))
            assert not pipeline._answer_ready.is_set()
            pipeline._submit(Transcript("Como funciona?", 0, True))
            assert pipeline._answer_ready.is_set()
            assert pipeline._pending.final
        finally:
            await pipeline.stop()
    asyncio.run(scenario())


def test_segmenter_bounds_continuous_audio_and_rejects_clicks():
    segmenter = SpeechSegmenter()
    for second in range(1, 31):
        result = segmenter.feed(audio(1))
        if second % 4 == 0 or second == 30:
            assert result.audio.duration == second
            assert not result.final
            assert result.boundary == (second == 30)
        else:
            assert result is None
    final = segmenter.feed(audio(1, 0))
    assert final.final and final.utterance_id == 0 and final.window_id == 1
    assert segmenter.feed(audio(0.05)) is None
    assert segmenter.feed(audio(1, 0)) is None


class Socket:
    def __init__(self):
        self.events = []

    async def send_json(self, event):
        self.events.append(event)


async def wait_until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.01)


def test_transcription_then_real_answer_protocol(monkeypatch):
    monkeypatch.setattr("backend.app.transcription.transcriber.transcribe", lambda chunk: "O que é Python?")

    async def stream(question, *, provisional=False):
        assert question == "O que é Python?"
        yield "Uma linguagem."

    monkeypatch.setattr("backend.app.simulator.stream_answer", stream)

    async def scenario():
        socket = Socket()
        session = Session("test", socket)
        pipeline = SpeechPipeline(SessionManager(), session)
        try:
            pipeline.feed(audio(1))
            pipeline.feed(audio(1, 0))
            await wait_until(lambda: any(e["type"] == "answer.completed" for e in socket.events))
            types = [e["type"] for e in socket.events]
            assert types.index("transcription.completed") < types.index("question.detected") < types.index("answer.delta")
            assert next(e for e in socket.events if e["type"] == "question.detected")["simulated"] is False
            sequence = [e["sequence"] for e in socket.events if "sequence" in e]
            assert sequence == sorted(set(sequence))
        finally:
            await pipeline.stop()

    asyncio.run(scenario())


def test_stop_discards_inflight_transcription(monkeypatch):
    started, release = threading.Event(), threading.Event()

    def transcribe(chunk):
        started.set()
        release.wait(3)
        return "Não deve aparecer"

    monkeypatch.setattr("backend.app.transcription.transcriber.transcribe", transcribe)

    async def scenario():
        socket = Socket()
        pipeline = SpeechPipeline(SessionManager(), Session("test", socket))
        pipeline.feed(audio(1))
        pipeline.feed(audio(1, 0))
        try:
            await wait_until(started.is_set)
            await pipeline.stop()
        finally:
            release.set()
        await asyncio.sleep(0.05)
        assert not any(e["type"] == "transcription.completed" for e in socket.events)

    asyncio.run(scenario())


def test_transcription_error_and_queue_bound(monkeypatch):
    def fail(chunk):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr("backend.app.transcription.transcriber.transcribe", fail)

    async def scenario():
        socket = Socket()
        pipeline = SpeechPipeline(SessionManager(), Session("test", socket))
        try:
            for index in range(10):
                pipeline._enqueue(SpeechSnapshot(audio(1), index, True))
            assert pipeline._queue.qsize() == 4
            await wait_until(lambda: any(e.get("code") == "transcription_failed" for e in socket.events))
            assert any(e.get("code") == "speech_overflow" for e in socket.events)
            assert not any(e["type"] == "answer.started" for e in socket.events)
        finally:
            await pipeline.stop()

    asyncio.run(scenario())


def test_transcription_keeps_running_during_answer_and_pending_uses_latest(monkeypatch):
    monkeypatch.setattr("backend.app.transcription.transcriber.transcribe", lambda chunk: f"Pergunta {chunk.duration}")

    async def scenario():
        release = asyncio.Event()
        calls = []

        async def stream(question, *, provisional=False):
            calls.append((question, provisional))
            yield "Resposta inicial"
            await release.wait()
            yield " concluída"

        monkeypatch.setattr("backend.app.simulator.stream_answer", stream)
        socket = Socket()
        pipeline = SpeechPipeline(SessionManager(), Session("test", socket))
        try:
            pipeline.feed(audio(4))  # No silence or finalization before the answer.
            await wait_until(lambda: any(e["type"] == "answer.delta" for e in socket.events))
            pipeline.feed(audio(4))
            await wait_until(lambda: any(e.get("text") == "Pergunta 8.0" for e in socket.events))
            pipeline.feed(audio(4))
            await wait_until(lambda: any(e.get("text") == "Pergunta 12.0" for e in socket.events))
            assert not any(e["type"] == "answer.completed" for e in socket.events)
            assert all(not e["final"] for e in socket.events if e["type"] == "transcription.completed")
            release.set()
            await wait_until(lambda: len(calls) == 2)
            assert calls == [("Pergunta 4.0", True), ("Pergunta 12.0", True)]
        finally:
            release.set()
            await pipeline.stop()

    asyncio.run(scenario())


def test_pending_audio_snapshots_are_coalesced_and_final_is_retained():
    async def scenario():
        pipeline = SpeechPipeline(SessionManager(), Session("test", Socket()))
        try:
            for duration in (4, 8, 12):
                pipeline._enqueue(SpeechSnapshot(audio(duration), 0, False))
            pipeline._enqueue(SpeechSnapshot(audio(13), 0, True))
            assert pipeline._queue.qsize() == 1
            assert pipeline._queue.get_nowait().final
        finally:
            await pipeline.stop()

    asyncio.run(scenario())


def test_stop_cancels_answer_and_prevents_late_deltas(monkeypatch):
    monkeypatch.setattr("backend.app.transcription.transcriber.transcribe", lambda chunk: "Pergunta clara")

    async def scenario():
        release = asyncio.Event()

        async def stream(question, *, provisional=False):
            yield "Primeira parte"
            await release.wait()
            yield "Parte atrasada"

        monkeypatch.setattr("backend.app.simulator.stream_answer", stream)
        socket = Socket()
        pipeline = SpeechPipeline(SessionManager(), Session("test", socket))
        pipeline.feed(audio(4))
        await wait_until(lambda: any(e["type"] == "answer.delta" for e in socket.events))
        await pipeline.stop()
        release.set()
        await asyncio.sleep(0.01)
        assert not any(e.get("delta") == "Parte atrasada" for e in socket.events)
        assert pipeline._worker.done() and pipeline._answer_worker.done()

    asyncio.run(scenario())


def test_continuous_windows_preserve_question_context(monkeypatch):
    texts = iter(["Como indexar email no PostgreSQL?", "A tabela tem milhões de registros."])
    monkeypatch.setattr("backend.app.transcription.transcriber.transcribe", lambda chunk: next(texts))

    async def stream(question, *, provisional=False):
        yield "Resposta"

    monkeypatch.setattr("backend.app.simulator.stream_answer", stream)

    async def scenario():
        socket = Socket()
        pipeline = SpeechPipeline(SessionManager(), Session("test", socket))
        try:
            pipeline._enqueue(SpeechSnapshot(audio(1), 0, False, 0, True))
            await wait_until(lambda: len([e for e in socket.events if e["type"] == "transcription.completed"]) == 1)
            pipeline._enqueue(SpeechSnapshot(audio(1), 0, True, 1))
            await wait_until(lambda: len([e for e in socket.events if e["type"] == "transcription.completed"]) == 2)
            final = [e for e in socket.events if e["type"] == "transcription.completed"][-1]
            assert final["final"]
            assert final["text"] == "Como indexar email no PostgreSQL? A tabela tem milhões de registros."
        finally:
            await pipeline.stop()

    asyncio.run(scenario())


@pytest.fixture(autouse=True)
def local_transcription_double(monkeypatch):
    async def transcribe(chunk):
        return await asyncio.to_thread(transcriber.transcribe, chunk)
    monkeypatch.setattr("backend.app.speech_pipeline.transcribe_audio", transcribe)
