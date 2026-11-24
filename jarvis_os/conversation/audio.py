"""Audio I/O for conversation mode: sounddevice mic capture, Silero VAD and a gapless, interruptible player."""
from __future__ import annotations

import asyncio
import threading
import time
from typing import AsyncIterator, Callable

import numpy as np

RATE = 16000


class MicSource:
    """Continuous 16 kHz mono capture in small frames (512 samples = 32 ms)."""

    def __init__(self, frame_samples: int = 512, device=None):
        self.frame_samples, self.device = frame_samples, device

    async def frames(self) -> AsyncIterator[np.ndarray]:
        import sounddevice as sd
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue(maxsize=200)

        def cb(indata, _frames, _time, status):
            frame = indata[:, 0].copy()
            try:
                loop.call_soon_threadsafe(q.put_nowait, frame)
            except (RuntimeError, asyncio.QueueFull):
                pass

        with sd.InputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=self.frame_samples,
                            device=self.device, callback=cb, latency="low"):
            while True:
                yield await q.get()


class ArraySource:
    """Feeds recorded PCM in real time, then silence. Used by tests and the synthetic latency test."""

    def __init__(self, pcm: np.ndarray, frame_samples: int = 512, lead_silence_s: float = 0.3,
                 speed: float = 1.0):
        self.pcm, self.n, self.lead, self.speed = pcm.astype(np.int16), frame_samples, lead_silence_s, speed
        self.audio_end: float | None = None      # monotonic time the last real sample was delivered

    async def frames(self):
        dt = self.n / RATE / self.speed
        silence = np.zeros(self.n, np.int16)
        chunks = [silence] * int(self.lead * RATE / self.n)
        chunks += [self.pcm[i:i + self.n] for i in range(0, len(self.pcm) - self.n + 1, self.n)]
        t0 = time.monotonic()
        k = 0
        while True:                     # paced against the clock, like a real sound card
            k += 1
            await asyncio.sleep(max(0.0, t0 + k * dt - time.monotonic()))
            if k <= len(chunks):
                yield chunks[k - 1]
                if k == len(chunks):
                    self.audio_end = time.monotonic()
            else:
                yield silence


class SileroVAD:
    """Silero speech probability per frame (the ONNX model shipped with openWakeWord; no torch needed).
    Falls back to an adaptive energy detector if it can't load."""

    def __init__(self):
        try:
            from openwakeword.vad import VAD
            self.model = VAD()
        except Exception as e:
            print(f"[conv] Silero VAD unavailable ({e}); using an energy detector")
            self.model = None
        self.floor = 300.0

    def __call__(self, frame: np.ndarray) -> float:
        if self.model is not None:
            return float(self.model.predict(frame, frame_size=len(frame)))
        rms = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)))
        self.floor = min(self.floor * 1.002 + 0.5, rms) if rms < self.floor * 3 else self.floor
        return float(np.clip((rms / max(self.floor, 30) - 1.5) / 3, 0, 1))


class Player:
    """One open output stream; clips are written in 40 ms slices so stop() takes effect almost at once
    and consecutive sentences play back to back without gaps."""
    RATE = 24000

    def __init__(self, device=None):
        import sounddevice as sd
        self.stream = sd.OutputStream(samplerate=self.RATE, channels=1, dtype="float32", device=device,
                                      latency="low")
        self.stream.start()
        self.level = 0.0
        self._lock = threading.Lock()

    @property
    def output_latency(self) -> float:
        return float(self.stream.latency or 0.0)

    def play(self, samples: np.ndarray, rate: int, valid: Callable[[], bool],
             on_start: Callable[[], None] | None = None) -> bool:
        """Blocking. Returns False if playback was cut short because valid() went False."""
        if rate != self.RATE and len(samples):
            n = int(len(samples) * self.RATE / rate)
            samples = np.interp(np.linspace(0, len(samples) - 1, n), np.arange(len(samples)), samples)
        samples = samples.astype(np.float32)
        step = self.RATE // 25
        with self._lock:
            for i in range(0, len(samples), step):
                if not valid():
                    self.level = 0.0
                    return False
                part = samples[i:i + step]
                self.level = min(1.0, float(np.sqrt(np.mean(part ** 2))) * 6)
                self.stream.write(part.reshape(-1, 1))
                if i == 0 and on_start:
                    on_start()
        self.level = 0.0
        return True

    def close(self):
        try:
            self.stream.stop()
            self.stream.close()
        except Exception:
            pass


class NullPlayer:
    """Test player: 'plays' instantly (or in real time with realtime=True)."""
    level = 0.0
    output_latency = 0.0

    def __init__(self, realtime: bool = False):
        self.realtime, self.played = realtime, []

    def play(self, samples, rate, valid, on_start=None):
        if on_start:
            on_start()
        self.played.append(len(samples) / rate)
        end = time.monotonic() + (len(samples) / rate if self.realtime else 0)
        while time.monotonic() < end:
            if not valid():
                return False
            time.sleep(0.01)
        return valid()

    def close(self): ...
