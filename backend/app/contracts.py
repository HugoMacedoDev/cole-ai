from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

PROTOCOL_VERSION = 1


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat()


class Event(BaseModel):
    version: Literal[1] = PROTOCOL_VERSION
    type: str
    session_id: str
    emitted_at: str = Field(default_factory=utc_timestamp)


class SessionStarted(Event):
    type: Literal["session.started"] = "session.started"


class QuestionDetected(Event):
    type: Literal["question.detected"] = "question.detected"
    question_id: str
    revision: int = 1
    sequence: int
    text: str
    simulated: bool = True


class AnswerStarted(Event):
    type: Literal["answer.started"] = "answer.started"
    question_id: str
    revision: int = 1
    sequence: int


class AnswerDelta(Event):
    type: Literal["answer.delta"] = "answer.delta"
    question_id: str
    revision: int = 1
    sequence: int
    delta: str


class AnswerCompleted(Event):
    type: Literal["answer.completed"] = "answer.completed"
    question_id: str
    revision: int = 1
    sequence: int


class AnswerCancelled(Event):
    type: Literal["answer.cancelled"] = "answer.cancelled"
    question_id: str
    revision: int = 1
    sequence: int


class SessionError(Event):
    type: Literal["session.error"] = "session.error"
    code: str
    message: str


class AudioCaptureStarted(Event):
    type: Literal["audio.capture.started"] = "audio.capture.started"


class AudioLevel(Event):
    type: Literal["audio.level"] = "audio.level"
    sequence: int
    level: float = Field(ge=0, le=1)


class AudioCaptureStopped(Event):
    type: Literal["audio.capture.stopped"] = "audio.capture.stopped"

