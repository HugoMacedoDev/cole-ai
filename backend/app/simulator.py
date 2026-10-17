from __future__ import annotations

import asyncio
import logging
import os
import time
from uuid import uuid4

from .contracts import AnswerActivity, AnswerCompleted, AnswerDelta, AnswerStarted, QuestionDetected
from .session import Session, SessionManager
from .answer_provider import stream_answer
from .provider_errors import AnswerProviderError

QUESTION = "Como você faria uma migração de banco de dados sem interromper a aplicação?"
ANSWER_PARTS = (
    "Usaria migrações versionadas e compatíveis com a aplicação atual, ",
    "executadas gradualmente e com possibilidade de rollback.",
)
logger = logging.getLogger(__name__)


def delay_seconds() -> float:
    return max(0, int(os.getenv("COLA_SIMULATION_DELAY_MS", "120"))) / 1000


async def run_simulation(manager: SessionManager, session: Session) -> None:
    question_id = str(uuid4())
    sequence = manager.next_sequence(session)
    await asyncio.sleep(delay_seconds())
    if session.cancelled:
        return
    await manager.send(session, QuestionDetected(
        session_id=session.id, question_id=question_id, sequence=sequence, text=QUESTION
    ))
    sequence = manager.next_sequence(session)
    await asyncio.sleep(delay_seconds())
    await manager.send(session, AnswerStarted(
        session_id=session.id, question_id=question_id, sequence=sequence
    ))
    for part in ANSWER_PARTS:
        sequence = manager.next_sequence(session)
        await asyncio.sleep(delay_seconds())
        if session.cancelled:
            return
        await manager.send(session, AnswerDelta(
            session_id=session.id, question_id=question_id, sequence=sequence, delta=part
        ))
    sequence = manager.next_sequence(session)
    await manager.send(session, AnswerCompleted(
        session_id=session.id, question_id=question_id, sequence=sequence
    ))


async def answer_question(manager: SessionManager, session: Session, question: str, *, provisional: bool = False) -> None:
    await manager.send(session, AnswerActivity(session_id=session.id, active=True, provisional=provisional))
    try:
        await _stream_question(manager, session, question, provisional=provisional)
    finally:
        await manager.send(session, AnswerActivity(session_id=session.id, active=False, provisional=provisional))


async def _stream_question(manager: SessionManager, session: Session, question: str, *, provisional: bool) -> None:
    question_id = str(uuid4())
    revision = 1
    started = False
    requested_at = time.monotonic_ns()
    try:
        async for delta in stream_answer(question, provisional=provisional):
            if session.cancelled:
                return
            if not started:
                logger.info("answer_first_delta latency_ms=%.1f provisional=%s",
                            (time.monotonic_ns() - requested_at) / 1_000_000, provisional)
                # Preserve the previous visible answer until replacement text exists.
                await manager.send(session, QuestionDetected(
                    session_id=session.id, question_id=question_id, revision=revision,
                    sequence=manager.next_sequence(session), text=question,
                    simulated=False, provisional=provisional,
                ))
                await manager.send(session, AnswerStarted(
                    session_id=session.id, question_id=question_id, revision=revision,
                    sequence=manager.next_sequence(session),
                ))
                started = True
            await manager.send(session, AnswerDelta(
                session_id=session.id,
                question_id=question_id,
                revision=revision,
                sequence=manager.next_sequence(session),
                delta=delta,
            ))
    except AnswerProviderError as error:
        from .contracts import SessionError
        await manager.send(session, SessionError(
            session_id=session.id, code="model_unavailable", message=str(error)
        ))
        return
    if not started:
        return
    logger.info("answer_completed latency_ms=%.1f provisional=%s",
                (time.monotonic_ns() - requested_at) / 1_000_000, provisional)
    await manager.send(session, AnswerCompleted(
        session_id=session.id,
        question_id=question_id,
        revision=revision,
        sequence=manager.next_sequence(session),
    ))
