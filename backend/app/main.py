from __future__ import annotations

import asyncio
import json
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .audio_capture import AudioCaptureError, WasapiLoopbackCapture
from .contracts import (
    AnswerCancelled,
    AudioCaptureStarted,
    AudioCaptureStopped,
    AudioLevel,
    SessionError,
    SessionStarted,
)
from .ollama import available as ollama_available, ollama_model
from .session import SessionManager
from .simulator import answer_question, run_simulation

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
)
logger = logging.getLogger(__name__)
app = FastAPI(title="Cola AI local backend", version="0.1.0")
sessions = SessionManager()


async def forward_audio_levels(manager: SessionManager, session, levels: asyncio.Queue[float]) -> None:
    while True:
        level = await levels.get()
        await manager.send(session, AudioLevel(
            session_id=session.id, sequence=manager.next_sequence(session), level=level
        ))
        await asyncio.sleep(0.08)


async def start_audio_capture(session) -> None:
    if session.audio_capture and session.audio_capture.active:
        return
    levels: asyncio.Queue[float] = asyncio.Queue(maxsize=1)
    loop = asyncio.get_running_loop()

    def push_level(level: float) -> None:
        def add_level() -> None:
            if levels.full():
                levels.get_nowait()
            levels.put_nowait(level)
        loop.call_soon_threadsafe(add_level)

    capture = WasapiLoopbackCapture(push_level)
    await asyncio.to_thread(capture.start)
    session.audio_capture = capture
    session.audio_task = asyncio.create_task(forward_audio_levels(sessions, session, levels))


@app.get("/health")
async def health() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "service": "cola-ai-backend",
        "ollama_available": await ollama_available(),
        "ollama_model": ollama_model(),
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    session = await sessions.create(websocket)
    try:
        while True:
            raw_message = await websocket.receive_text()
            try:
                message = json.loads(raw_message)
            except json.JSONDecodeError:
                await sessions.send(session, SessionError(
                    session_id=session.id, code="invalid_json", message="Mensagem deve ser JSON válido."
                ))
                continue
            if message.get("type") == "session.start":
                await sessions.send(session, SessionStarted(session_id=session.id))
            elif message.get("type") == "question.ask":
                question = str(message.get("text", "")).strip()
                if not question:
                    await sessions.send(session, SessionError(
                        session_id=session.id, code="empty_question", message="Informe uma pergunta para a IA."
                    ))
                elif session.task is None or session.task.done():
                    session.cancelled = False
                    session.task = asyncio.create_task(answer_question(sessions, session, question))
            elif message.get("type") == "simulation.start":
                if session.task is None or session.task.done():
                    session.cancelled = False
                    session.task = asyncio.create_task(run_simulation(sessions, session))
            elif message.get("type") == "audio.capture.start":
                try:
                    await start_audio_capture(session)
                    await sessions.send(session, AudioCaptureStarted(session_id=session.id))
                except AudioCaptureError as error:
                    await sessions.send(session, SessionError(
                        session_id=session.id, code="audio_capture_failed", message=str(error)
                    ))
            elif message.get("type") == "audio.capture.stop":
                if session.audio_task and not session.audio_task.done():
                    session.audio_task.cancel()
                if session.audio_capture:
                    await asyncio.to_thread(session.audio_capture.stop)
                    session.audio_capture = None
                await sessions.send(session, AudioCaptureStopped(session_id=session.id))
            elif message.get("type") == "answer.cancel":
                await sessions.cancel(session)
                await sessions.send(session, AnswerCancelled(
                    session_id=session.id,
                    question_id=str(message.get("question_id", "unknown")),
                    sequence=int(message.get("sequence", 0)) + 1,
                ))
            else:
                await sessions.send(session, SessionError(
                    session_id=session.id, code="unknown_event", message="Evento de cliente não suportado."
                ))
    except WebSocketDisconnect:
        logger.info("client_disconnected", extra={"session_id": session.id})
    except Exception:
        logger.exception("websocket_failure", extra={"session_id": session.id})
    finally:
        await sessions.remove(session)
