from __future__ import annotations

import audioop
import io
import os
import threading
import wave
from dataclasses import dataclass
from typing import Any

from .technical_assistant import TRANSCRIPTION_CONTEXT


@dataclass(frozen=True)
class AudioChunk:
    pcm: bytes
    sample_rate: int
    channels: int

    @property
    def duration(self) -> float:
        return len(self.pcm) / (self.sample_rate * self.channels * 2)


@dataclass(frozen=True)
class SpeechSnapshot:
    audio: AudioChunk
    utterance_id: int
    final: bool
    window_id: int = 0
    boundary: bool = False


class SpeechSegmenter:
    """Emit cumulative snapshots during speech, then finalize on silence."""

    def __init__(self) -> None:
        self._parts: list[bytes] = []
        self._duration = 0.0
        self._silence = 0.0
        self._voiced = 0.0
        self._last_emitted = 0.0
        self._utterance_id = 0
        self._window_id = 0
        self._active = False

    def feed(self, chunk: AudioChunk) -> SpeechSnapshot | None:
        voiced = audioop.rms(chunk.pcm, 2) >= 250
        if not voiced and not self._parts and not self._active:
            return None
        if voiced:
            self._active = True
        self._parts.append(chunk.pcm)
        self._duration += chunk.duration
        self._voiced += chunk.duration if voiced else 0
        self._silence = 0 if voiced else self._silence + chunk.duration
        final = self._silence >= 0.8
        boundary = self._duration >= 30
        if not final and not boundary and self._duration - self._last_emitted < 4:
            return None
        result = SpeechSnapshot(
            AudioChunk(b"".join(self._parts), chunk.sample_rate, chunk.channels),
            self._utterance_id, final, self._window_id, boundary,
        )
        enough_speech = self._voiced >= 0.3 or self._window_id > 0
        self._last_emitted = self._duration
        if final or boundary:
            self._parts.clear()
            self._duration = self._silence = self._voiced = self._last_emitted = 0
        if final:
            self._utterance_id += 1
            self._window_id = 0
            self._active = False
        elif boundary:
            self._window_id += 1
        return result if enough_speech else None


class LocalTranscriber:
    """One lazily loaded CPU model, serialized across sessions."""

    def __init__(self) -> None:
        self._model: Any | None = None
        self._lock = threading.Lock()

    def transcribe(self, chunk: AudioChunk) -> str:
        from faster_whisper import WhisperModel

        with self._lock:
            if self._model is None:
                self._model = WhisperModel(
                    os.getenv("COLA_WHISPER_MODEL", "small"), device="cpu", compute_type="int8"
                )
            audio = io.BytesIO()
            with wave.open(audio, "wb") as wav:
                wav.setnchannels(chunk.channels)
                wav.setsampwidth(2)
                wav.setframerate(chunk.sample_rate)
                wav.writeframes(chunk.pcm)
            audio.seek(0)
            segments, _ = self._model.transcribe(
                audio, language=os.getenv("COLA_TRANSCRIPTION_LANGUAGE", "pt"),
                vad_filter=True, beam_size=5, temperature=0, condition_on_previous_text=False,
                initial_prompt=TRANSCRIPTION_CONTEXT,
            )
            return " ".join(
                segment.text.strip() for segment in segments
                if segment.text.strip() and segment.avg_logprob >= -1
                and segment.compression_ratio <= 2.4
            )


transcriber = LocalTranscriber()
