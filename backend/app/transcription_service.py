from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path
import subprocess
import sys

from .transcription import AudioChunk


class TranscriptionService:
    """Isolate native inference from WASAPI's Python reader and the event loop."""

    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._requests: set[asyncio.Task[str]] = set()

    async def transcribe(self, chunk: AudioChunk) -> str:
        task = asyncio.create_task(self._request(chunk))
        self._requests.add(task)
        task.add_done_callback(self._finished)
        # Cancellation must not leave an unread response for the next request.
        return await asyncio.shield(task)

    def _finished(self, task: asyncio.Task[str]) -> None:
        self._requests.discard(task)
        if not task.cancelled():
            task.exception()

    async def _request(self, chunk: AudioChunk) -> str:
        async with self._lock:
            if self._process is None or self._process.returncode is not None:
                self._process = await asyncio.create_subprocess_exec(
                    sys.executable, "-u", "-m", "backend.app.transcription_worker",
                    cwd=str(Path(__file__).resolve().parents[2]),
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            process = self._process
            assert process.stdin is not None and process.stdout is not None
            request = {"pcm": base64.b64encode(chunk.pcm).decode("ascii"),
                       "sample_rate": chunk.sample_rate, "channels": chunk.channels}
            try:
                process.stdin.write(json.dumps(request).encode("utf-8") + b"\n")
                await process.stdin.drain()
                async with asyncio.timeout(120):
                    raw = await process.stdout.readline()
                if not raw:
                    raise RuntimeError("O processo de transcrição foi encerrado.")
                result = json.loads(raw)
                if result.get("error"):
                    raise RuntimeError(result["error"])
                return str(result["text"])
            except BaseException:
                await self._close_process()
                raise

    async def _close_process(self) -> None:
        process, self._process = self._process, None
        if process is not None:
            if process.returncode is None:
                process.kill()
            await process.wait()

    async def close(self) -> None:
        for task in list(self._requests):
            task.cancel()
        await asyncio.gather(*list(self._requests), return_exceptions=True)
        await self._close_process()


service = TranscriptionService()


async def transcribe_audio(chunk: AudioChunk) -> str:
    return await service.transcribe(chunk)
