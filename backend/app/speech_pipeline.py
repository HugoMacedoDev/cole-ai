from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Literal

from .contracts import SessionError, TranscriptionCompleted, TranscriptionStatus
from .session import Session, SessionManager
from .simulator import answer_question
from .transcription import AudioChunk, SpeechSegmenter, SpeechSnapshot
from .transcription_service import transcribe_audio

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Transcript:
    text: str
    utterance_id: int
    final: bool


class SpeechPipeline:
    def __init__(self, manager: SessionManager, session: Session) -> None:
        self.manager = manager
        self.session = session
        self._loop = asyncio.get_running_loop()
        self._segmenter = SpeechSegmenter()
        self._queue: asyncio.Queue[SpeechSnapshot] = asyncio.Queue(maxsize=4)
        self._closed = False
        self._overflow_reported = False
        self._pending: Transcript | None = None
        self._last_submitted: Transcript | None = None
        self._answer_ready = asyncio.Event()
        self._answer_task: asyncio.Task[None] | None = None
        self._active_final = False
        self._prefix = ""
        self._transcript_utterance = -1
        self._worker = asyncio.create_task(self._transcribe())
        self._answer_worker = asyncio.create_task(self._answer())

    def feed(self, chunk: AudioChunk) -> None:
        """Capture thread emits snapshots without waiting for ASR or answers."""
        if self._closed:
            return
        snapshot = self._segmenter.feed(chunk)
        if snapshot is not None:
            self._loop.call_soon_threadsafe(self._enqueue, snapshot)

    def _enqueue(self, snapshot: SpeechSnapshot) -> None:
        if self._closed:
            return
        pending: list[SpeechSnapshot] = []
        while not self._queue.empty():
            old = self._queue.get_nowait()
            if (old.utterance_id, old.window_id) != (snapshot.utterance_id, snapshot.window_id):
                pending.append(old)
        if len(pending) == self._queue.maxsize:
            pending.pop(0)
            self._overflow_reported = True
        for old in pending:
            self._queue.put_nowait(old)
        self._queue.put_nowait(snapshot)

    async def stop(self) -> None:
        self._closed = True
        self._pending = None
        tasks = [self._worker, self._answer_worker]
        if self._answer_task:
            tasks.append(self._answer_task)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        while not self._queue.empty():
            self._queue.get_nowait()

    async def _status(self, status: Literal["listening", "transcribing", "error"]) -> None:
        await self.manager.send(self.session, TranscriptionStatus(session_id=self.session.id, status=status))

    def _submit(self, transcript: Transcript) -> None:
        transcript = Transcript(" ".join(transcript.text.split()), transcript.utterance_id, transcript.final)
        if transcript == self._last_submitted:
            return
        # Replace pending work instead of accumulating stale answers.
        self._last_submitted = transcript
        self._pending = transcript
        if self._active_final and self._answer_task and not self._answer_task.done():
            self._answer_task.cancel()
        self._answer_ready.set()

    async def _transcribe(self) -> None:
        while True:
            snapshot = await self._queue.get()
            try:
                if self._overflow_reported:
                    self._overflow_reported = False
                    await self.manager.send(self.session, SessionError(
                        session_id=self.session.id, code="speech_overflow",
                        message="Processamento atrasado: um trecho antigo foi descartado.",
                    ))
                await self._status("transcribing")
                started = time.monotonic_ns()
                text = await transcribe_audio(snapshot.audio)
                elapsed_ms = (time.monotonic_ns() - started) / 1_000_000
                if snapshot.utterance_id != self._transcript_utterance:
                    self._prefix = ""
                    self._transcript_utterance = snapshot.utterance_id
                combined = " ".join(part for part in (self._prefix, text) if part)
                if snapshot.boundary:
                    self._prefix = combined[-6000:]
                if combined:
                    await self.manager.send(self.session, TranscriptionCompleted(
                        session_id=self.session.id, text=combined, latency_ms=elapsed_ms,
                        sequence=self.manager.next_sequence(self.session), final=snapshot.final,
                    ))
                    self._submit(Transcript(combined, snapshot.utterance_id, snapshot.final))
                await self._status("listening")
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("speech_transcription_failed")
                await self._status("error")
                await self.manager.send(self.session, SessionError(
                    session_id=self.session.id, code="transcription_failed",
                    message="Falha na transcrição local. Verifique a instalação e o modelo Whisper.",
                ))

    async def _answer(self) -> None:
        while True:
            await self._answer_ready.wait()
            if self.session.task and not self.session.task.done():
                await asyncio.gather(asyncio.shield(self.session.task), return_exceptions=True)
            self._answer_ready.clear()
            transcript, self._pending = self._pending, None
            if transcript is None:
                continue
            self.session.cancelled = False
            self._active_final = transcript.final
            self._answer_task = asyncio.create_task(answer_question(
                self.manager, self.session, transcript.text, provisional=not transcript.final,
            ))
            self.session.task = self._answer_task
            try:
                await self._answer_task
            except asyncio.CancelledError:
                if self._closed:
                    raise
            except Exception:
                logger.exception("speech_answer_failed")
                await self.manager.send(self.session, SessionError(
                    session_id=self.session.id, code="answer_failed",
                    message="Falha ao gerar a resposta. A transcrição continua ativa.",
                ))
            finally:
                self._active_final = False
