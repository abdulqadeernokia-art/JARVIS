"""Text-to-speech: neural male voice (edge-tts), synthesising sentence N+1 while N plays; instant interrupt.
Falls back to the offline Windows voice when there's no internet."""
from __future__ import annotations

import asyncio
import os
import queue
import re
import tempfile
import threading
from typing import Callable

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")


class Speaker:
    def __init__(self, voice: str = "en-GB-RyanNeural", on_state: Callable[[bool, str], None] | None = None):
        import pygame
        pygame.mixer.init()
        self.pg = pygame
        self.voice = voice
        self.on_state = on_state or (lambda speaking, text: None)
        self._text_q: queue.Queue = queue.Queue()
        self._audio_q: queue.Queue = queue.Queue()
        self._pending = 0
        self._lock = threading.Lock()
        self._idle = threading.Event()
        self._idle.set()
        self._gen = 0          # generation counter: interrupt() invalidates everything queued before it
        self._words: list[tuple[float, float]] = []   # (start_s, end_s) of words in the clip now playing
        self._clip_start = 0.0
        threading.Thread(target=self._synth_loop, daemon=True, name="tts-synth").start()
        threading.Thread(target=self._play_loop, daemon=True, name="tts-play").start()

    @property
    def speaking(self) -> bool:
        return not self._idle.is_set()

    def say(self, text: str) -> None:
        text = re.sub(r"[*_#`>|]+", "", text).strip()
        if not text:
            return
        print(f"JARVIS: {text}")
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
            if sentence.strip():
                with self._lock:
                    self._pending += 1
                    self._idle.clear()
                self._text_q.put((self._gen, sentence.strip()))

    @property
    def level(self) -> float:
        """Speech envelope (0..1) of what is playing right now, from edge-tts word timings."""
        import time
        if not self.speaking or not self._words:
            return 0.0
        t = time.monotonic() - self._clip_start
        for a, b in self._words:
            if a - 0.03 <= t <= b + 0.03:
                mid = (a + b) / 2
                half = max(0.05, (b - a) / 2)
                return max(0.35, 1.0 - abs(t - mid) / half * 0.6)
        return 0.08

    def wait(self, timeout: float | None = None) -> bool:
        return self._idle.wait(timeout)

    def interrupt(self) -> None:
        with self._lock:
            self._gen += 1
        try:
            self.pg.mixer.music.stop()
        except Exception:
            pass

    def _done(self):
        with self._lock:
            self._pending = max(0, self._pending - 1)
            if self._pending == 0:
                self._idle.set()
                self.on_state(False, "")

    def _synth_loop(self):
        import edge_tts
        while True:
            gen, sentence = self._text_q.get()
            if gen != self._gen:
                self._done()
                continue
            fd, path = tempfile.mkstemp(suffix=".mp3")
            os.close(fd)
            try:
                words = asyncio.run(_synth(edge_tts, sentence, self.voice, path))
                self._audio_q.put((gen, sentence, path, words))
            except Exception as e:
                print(f"[tts] edge-tts failed, using offline voice: {e}")
                os.remove(path)
                self._audio_q.put((gen, sentence, None, []))

    def _play_loop(self):
        while True:
            gen, sentence, path, words = self._audio_q.get()
            if gen == self._gen:
                self.on_state(True, sentence)
                if path:
                    try:
                        self.pg.mixer.music.load(path)
                        self.pg.mixer.music.play()
                        import time
                        self._words, self._clip_start = words, time.monotonic()
                        while self.pg.mixer.music.get_busy() and gen == self._gen:
                            self.pg.time.wait(30)
                        self.pg.mixer.music.stop()
                        self.pg.mixer.music.unload()
                        self._words = []
                    except Exception as e:
                        print(f"[tts] playback error: {e}")
                else:
                    _offline_say(sentence)
            if path:
                try:
                    os.remove(path)
                except OSError:
                    pass
            self._done()


async def _synth(edge_tts, sentence: str, voice: str, path: str) -> list[tuple[float, float]]:
    """Write the mp3 and return word timings (seconds) for the visual speech envelope."""
    try:
        com = edge_tts.Communicate(sentence, voice, rate="+8%", boundary="WordBoundary")
    except TypeError:            # older edge-tts without the boundary option
        com = edge_tts.Communicate(sentence, voice, rate="+8%")
    words = []
    with open(path, "wb") as f:
        async for chunk in com.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                a = chunk["offset"] / 1e7
                words.append((a, a + chunk["duration"] / 1e7))
    return words


def _offline_say(text: str) -> None:
    import pyttsx3
    engine = pyttsx3.init()
    engine.setProperty("rate", 180)
    for v in engine.getProperty("voices"):
        if any(n in v.name.lower() for n in ("david", "mark", "george")):
            engine.setProperty("voice", v.id)
            break
    engine.say(text)
    engine.runAndWait()
    engine.stop()


def chime(kind: str = "wake") -> None:
    import winsound
    tones = {"wake": [(880, 60), (1320, 80)], "sleep": [(990, 60), (660, 80)], "error": [(300, 180)],
             "approval": [(660, 70), (880, 70), (660, 70)], "notify": [(1046, 90), (1318, 120)]}
    threading.Thread(target=lambda: [winsound.Beep(f, d) for f, d in tones[kind]], daemon=True).start()
