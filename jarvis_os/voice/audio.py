"""Microphone engine: one always-open 16 kHz stream, broadcast to any number of listeners.

Per 80 ms chunk it computes: loudness (for visuals), Silero speech probability (volume independent) and the
wake word. Wake word = the single word "Jarvis", spotted offline by Vosk restricted to a tiny grammar
(decoy words absorb sound-alikes), with openWakeWord's "hey jarvis" model as a second detector.
Recorders (commands, dictation, meeting mode) each get their own queue.
"""
from __future__ import annotations

import collections
import json
import queue
import threading
import time
from pathlib import Path
from typing import Callable

import numpy as np

RATE, CHUNK = 16000, 1280
CHUNK_S = CHUNK / RATE
VOSK_MODEL = Path(__file__).resolve().parents[2] / "data" / "models" / "vosk-model-small-en-us-0.15"
# Similar-sounding words compete with "jarvis" so they don't get forced into it.
DECOYS = ["travis", "service", "nervous", "marcus", "jars", "harvest", "garbage", "jarred", "carvings", "office",
          "chris", "purpose", "davis", "charges", "gervais"]


class WordSpotter:
    """Offline keyword spotting for 'jarvis' with Vosk."""

    def __init__(self, word: str = "jarvis"):
        import vosk
        vosk.SetLogLevel(-1)
        self.word = word
        self.model = vosk.Model(str(VOSK_MODEL))
        self.grammar = json.dumps([word] + [d for d in DECOYS if d != word] + ["[unk]"])
        self.rec = vosk.KaldiRecognizer(self.model, RATE, self.grammar)

    def feed(self, data: bytes) -> bool:
        if self.rec.AcceptWaveform(data):
            text = json.loads(self.rec.Result())["text"]
        else:
            text = json.loads(self.rec.PartialResult())["partial"]
        if self.word in text.split():
            self.rec.Reset()
            return True
        return False


class AudioEngine:
    def __init__(self, wake_threshold: float = 0.5):
        import pyaudio
        from openwakeword.model import Model
        from openwakeword.vad import VAD
        self.wake_model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
        self.spotter = WordSpotter() if VOSK_MODEL.exists() else None
        if not self.spotter:
            print(f"[audio] Vosk model missing at {VOSK_MODEL}; only 'hey jarvis' will wake me")
        self.vad = VAD()
        self.pa = pyaudio.PyAudio()
        self.stream = self.pa.open(format=pyaudio.paInt16, channels=1, rate=RATE, input=True,
                                   frames_per_buffer=CHUNK)
        self.device = self.pa.get_default_input_device_info()["name"]
        self.wake_threshold = wake_threshold
        self.level = 0.0
        self.paused = False                       # privacy mode: mic data is dropped
        self.on_wake: Callable[[], None] | None = None
        self._peak = 200.0
        self._subs: list[queue.Queue] = []
        self._lock = threading.Lock()
        self._preroll = collections.deque(maxlen=6)
        self._last_wake = 0.0
        self._stop = threading.Event()
        threading.Thread(target=self._loop, daemon=True, name="audio").start()

    def close(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            try:
                data = self.stream.read(CHUNK, exception_on_overflow=False)
            except OSError:
                time.sleep(0.1)
                continue
            if self.paused:
                self.level = 0.0
                continue
            pcm = np.frombuffer(data, dtype=np.int16)
            rms = float(np.sqrt(np.mean(pcm.astype(np.float32) ** 2)))
            self._peak = max(rms, self._peak * 0.995, 30.0)
            self.level = min(1.0, rms / self._peak)
            speech = float(self.vad.predict(pcm, frame_size=640))
            item = (data, speech, time.time())
            self._preroll.append(item)
            with self._lock:
                for q in self._subs:
                    q.put(item)
            score = self.wake_model.predict(pcm)["hey_jarvis"]
            spotted = self.spotter.feed(data) if self.spotter else False
            if (spotted or score > self.wake_threshold) and time.time() - self._last_wake > 1.5:
                self._last_wake = time.time()
                self.wake_model.reset()
                # keep only the last ~0.16 s so words said right after "Jarvis" aren't clipped,
                # but the name itself doesn't become part of the command
                tail = list(self._preroll)[-2:]
                self._preroll.clear()
                self._preroll.extend(tail)
                print(f"[audio] wake word ({'jarvis' if spotted else f'hey jarvis {score:.2f}'})")
                if self.on_wake:
                    self.on_wake()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def record(self, start_timeout: float = 6, silence: float = 1.3, max_seconds: float = 30,
               cancel: threading.Event | None = None, use_preroll: bool = True) -> bytes | None:
        """Record one utterance: wait for speech, stop after `silence` s of quiet. Returns raw PCM or None."""
        q = self.subscribe()
        pre = list(self._preroll) if use_preroll else []
        got: list[bytes] = []
        started, quiet, t0 = False, 0.0, time.time()
        try:
            while True:
                if cancel is not None and cancel.is_set():
                    return None
                try:
                    data, speech, _ = q.get(timeout=0.5)
                except queue.Empty:
                    if not started and time.time() - t0 > start_timeout:
                        return None
                    continue
                if not started:
                    pre = (pre + [(data, speech, 0)])[-6:]
                    if speech > 0.5:
                        started, got = True, [d for d, _, _ in pre]
                    elif time.time() - t0 > start_timeout:
                        return None
                    continue
                got.append(data)
                quiet = quiet + CHUNK_S if speech < 0.3 else 0.0
                if quiet >= silence or len(got) * CHUNK_S > max_seconds:
                    break
        finally:
            self.unsubscribe(q)
        return b"".join(got)


def normalise(pcm_bytes: bytes) -> bytes:
    """Boost quiet headset mics before transcription."""
    pcm = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
    peak = float(np.abs(pcm).max()) if pcm.size else 0.0
    if peak <= 0:
        return pcm_bytes
    gain = min(30000 / peak, 40.0)
    return np.clip(pcm * gain, -32768, 32767).astype(np.int16).tobytes()
