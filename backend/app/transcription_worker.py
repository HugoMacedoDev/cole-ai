"""Private JSON-lines worker. Audio is only held in memory; EOF exits with the parent."""
from __future__ import annotations

import base64
import json
import sys

from .transcription import AudioChunk, transcriber


def main() -> None:
    for raw in sys.stdin.buffer:
        try:
            request = json.loads(raw)
            audio = AudioChunk(base64.b64decode(request["pcm"]), request["sample_rate"], request["channels"])
            response = {"text": transcriber.transcribe(audio)}
        except Exception as error:
            response = {"error": str(error)}
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
