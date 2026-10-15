from __future__ import annotations

import asyncio
import os
from uuid import uuid4

from .contracts import AnswerCompleted, AnswerDelta, AnswerStarted, QuestionDetected
from .session import Session, SessionManager
from .ollama import OllamaUnavailableError, stream_answer

QUESTION = "Como você faria uma migração de banco de dados sem interromper a aplicação?"
ANSWER_PARTS = (
    "Usaria migrações versionadas e compatíveis com a aplicação atual, ",
    "executadas gradualmente e com possibilidade de rollback.",
)


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


async def answer_question(manager: SessionManager, session: Session, question: str) -> None:
    question_id = str(uuid4())
    revision = 1
    await manager.send(session, QuestionDetected(
        session_id=session.id,
        question_id=question_id,
        revision=revision,
        sequence=manager.next_sequence(session),
        text=question,
        simulated=False,
    ))
    await manager.send(session, AnswerStarted(
        session_id=session.id,
        question_id=question_id,
        revision=revision,
        sequence=manager.next_sequence(session),
    ))
    try:
        async for delta in stream_answer(question):
            if session.cancelled:
                return
            await manager.send(session, AnswerDelta(
                session_id=session.id,
                question_id=question_id,
                revision=revision,
                sequence=manager.next_sequence(session),
                delta=delta,
            ))
    except OllamaUnavailableError as error:
        from .contracts import SessionError
        await manager.send(session, SessionError(
            session_id=session.id, code="ollama_unavailable", message=str(error)
        ))
        return
    await manager.send(session, AnswerCompleted(
        session_id=session.id,
        question_id=question_id,
        revision=revision,
        sequence=manager.next_sequence(session),
    ))
