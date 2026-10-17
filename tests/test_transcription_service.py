import asyncio
import base64
import json
import struct

import pytest

from backend.app.transcription import AudioChunk
from backend.app.transcription_service import TranscriptionService


def test_cancelled_request_is_drained_before_next_transcription(monkeypatch):
    async def scenario():
        replies = asyncio.Queue()
        first_sent = asyncio.Event()
        release_first = asyncio.Event()
        writes = []

        class Input:
            def write(self, data):
                writes.append(json.loads(data))
                first_sent.set()

            async def drain(self):
                if len(writes) == 1:
                    await release_first.wait()
                await replies.put(json.dumps({"text": str(len(writes))}).encode())

        class Output:
            async def readline(self):
                return await replies.get()

        class Process:
            stdin = Input()
            stdout = Output()
            returncode = None

            def kill(self):
                self.returncode = 0

            async def wait(self):
                return 0

        async def create(*args, **kwargs):
            return Process()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
        service = TranscriptionService()
        audio = AudioChunk(struct.pack("<h", 1000) * 32, 16000, 1)
        first = asyncio.create_task(service.transcribe(audio))
        await first_sent.wait()
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        second = asyncio.create_task(service.transcribe(audio))
        release_first.set()
        try:
            assert await asyncio.wait_for(second, 2) == "2"
            assert base64.b64decode(writes[0]["pcm"]) == audio.pcm
        finally:
            await service.close()

    asyncio.run(scenario())
