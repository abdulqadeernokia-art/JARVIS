"""VoiceIO: the voice layer as seen by tools and the approval broker."""
from __future__ import annotations

import re
import threading
import time

from .audio import AudioEngine
from .speaker import Speaker, chime
from .stt import STT

YES = re.compile(r"\b(yes|yeah|yep|yup|sure|ok(ay)?|confirm(ed)?|do it|go ahead|send it|approve(d)?|affirmative|"
                 r"please do)\b", re.I)
NO = re.compile(r"\b(no|nope|don'?t|cancel|stop|wait|deny|negative|hold on|not yet)\b", re.I)


class VoiceIO:
    def __init__(self, audio: AudioEngine, stt: STT, speaker: Speaker, bus):
        self.audio, self.stt, self.speaker, self.bus = audio, stt, speaker, bus
        self._meeting_stop: threading.Event | None = None

    def say(self, text: str) -> None:
        self.speaker.say(text)

    def wait_spoken(self) -> None:
        self.speaker.wait()

    def listen_ex(self, start_timeout: float = 6, silence: float = 0.8, max_seconds: float = 30) -> tuple[str, bool]:
        """Returns (text, heard_speech). heard_speech=True but text='' means 'didn't understand'."""
        self.bus.publish("voice.state", state="listening")
        pcm = self.audio.record(start_timeout, silence, max_seconds)
        if not pcm:
            return "", False
        self.bus.publish("voice.state", state="transcribing")
        text = self.stt.transcribe(pcm).strip()
        if text:
            self.bus.publish("voice.transcript", text=text, partial=False)
        return text, True

    def listen(self, start_timeout: float = 6, silence: float = 0.8, max_seconds: float = 30) -> str:
        return self.listen_ex(start_timeout, silence, max_seconds)[0]

    # ---------- approvals ----------
    def ask_approval(self, req) -> str | None:
        chime("approval")
        self.speaker.say(f"I'd like to {req.summary}. Shall I go ahead?")
        self.speaker.wait()
        for _ in range(2):
            if req._done.is_set():
                return None
            answer = self.listen(8)
            if not answer:
                continue
            if NO.search(answer):
                return "denied"
            if YES.search(answer):
                return "approved"
            self.speaker.say("Sorry, yes or no?")
            self.speaker.wait()
        return None

    # ---------- meeting mode ----------
    def start_meeting(self, on_segment) -> None:
        stop = threading.Event()
        self._meeting_stop = stop

        def loop():
            while not stop.is_set():
                pcm = self.audio.record(start_timeout=30, silence=0.9, max_seconds=25, cancel=stop,
                                        use_preroll=False)
                if pcm:
                    t = time.time()
                    # transcribe off-thread so we keep listening while Google responds
                    threading.Thread(target=lambda p=pcm, ts=t: self._seg(p, ts, on_segment), daemon=True).start()

        threading.Thread(target=loop, daemon=True, name="meeting").start()

    def _seg(self, pcm, ts, on_segment):
        text = self.stt.transcribe(pcm)
        if text:
            on_segment(text, ts)

    def stop_meeting(self) -> None:
        if self._meeting_stop:
            self._meeting_stop.set()
            self._meeting_stop = None
