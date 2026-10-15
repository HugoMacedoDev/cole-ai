from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from fastapi import WebSocket

from .contracts import Event

logger = logging.getLogger(__name__)
SendEvent = Callable[[Event], Awaitable[None]]


@dataclass
class Session:
    id: str
    websocket: WebSocket
    task: asyncio.Task[None] | None = None
    cancelled: bool = False
    sequence: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    audio_capture: Any | None = None
    audio_task: asyncio.Task[None] | None = None


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    async def create(self, websocket: WebSocket) -> Session:
        session = Session(id=str(uuid4()), websocket=websocket)
        self._sessions[session.id] = session
        logger.info("session_created", extra={"session_id": session.id})
        return session

    async def send(self, session: Session, event: Event) -> None:
        async with session.lock:
            await session.websocket.send_json(event.model_dump())

    async def cancel(self, session: Session) -> None:
        session.cancelled = True
        if session.task and not session.task.done():
            session.task.cancel()

    def next_sequence(self, session: Session) -> int:
        session.sequence += 1
        return session.sequence

    async def remove(self, session: Session) -> None:
        await self.cancel(session)
        if session.audio_task and not session.audio_task.done():
            session.audio_task.cancel()
        if session.audio_capture:
            session.audio_capture.stop()
        self._sessions.pop(session.id, None)
        logger.info("session_removed", extra={"session_id": session.id})

