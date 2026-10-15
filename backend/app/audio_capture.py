from __future__ import annotations

import audioop
import math
import os
import threading
from collections.abc import Callable
from typing import Any


class AudioCaptureError(RuntimeError):
    """Raised when the Windows system-output capture cannot be started."""


class WasapiLoopbackCapture:
    """Captures Windows system output through the WASAPI loopback device."""

    def __init__(self, on_level: Callable[[float], None]) -> None:
        self._on_level = on_level
        self._audio: Any | None = None
        self._stream: Any | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._reader: threading.Thread | None = None
        self._chunk = 1024

    @property
    def active(self) -> bool:
        return self._stream is not None and self._stream.is_active()

    def start(self) -> None:
        if self.active:
            return
        try:
            import pyaudiowpatch as pyaudio
        except ImportError as error:
            raise AudioCaptureError("O componente de captura WASAPI não está instalado.") from error

        try:
            self._audio = pyaudio.PyAudio()
            device = self._audio.get_default_wasapi_loopback()
            self._chunk = max(256, int(os.getenv("COLA_AUDIO_CHUNK_FRAMES", "1024")))
            self._stream = self._audio.open(
                format=pyaudio.paInt16,
                channels=int(device["maxInputChannels"]),
                rate=int(device["defaultSampleRate"]),
                input=True,
                input_device_index=int(device["index"]),
                frames_per_buffer=self._chunk,
            )
            self._stream.start_stream()
            self._stop.clear()
            self._reader = threading.Thread(target=self._read_loop, name="cola-wasapi", daemon=True)
            self._reader.start()
        except Exception as error:
            self.stop()
            raise AudioCaptureError(f"Não foi possível iniciar WASAPI Loopback: {error}") from error

    def stop(self) -> None:
        with self._lock:
            stream, audio, reader = self._stream, self._audio, self._reader
            self._stream, self._audio = None, None
            self._reader = None
            self._stop.set()
        if stream is not None:
            try:
                if stream.is_active():
                    stream.stop_stream()
                stream.close()
            except Exception:
                pass
        if audio is not None:
            try:
                audio.terminate()
            except Exception:
                pass
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=1)

    def _read_loop(self) -> None:
        while not self._stop.is_set():
            stream = self._stream
            if stream is None:
                return
            try:
                data = stream.read(self._chunk, exception_on_overflow=False)
                rms = audioop.rms(data, 2)
                self._on_level(min(1.0, math.sqrt(rms / 32768)))
            except Exception:
                if not self._stop.is_set():
                    self._stop.set()
                return
