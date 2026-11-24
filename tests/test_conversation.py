"""Conversation mode pipeline, with fake audio (no mic, speakers, network or models)."""
import asyncio

import numpy as np

from jarvis_os.conversation import ConvConfig, ConversationSession
from jarvis_os.conversation.audio import NullPlayer
from jarvis_os.conversation.brains import Brain, EchoBrain
from jarvis_os.conversation.speech import SpeechToText, ToneTTS

N = 512


class ScriptSource:
    """Plays a script of ("speech", text, seconds) / ("silence", seconds) at 20x real time.
    Speech frames carry a marker so FakeVAD/FakeSTT can see them."""

    def __init__(self, script, speed=20.0):
        self.script, self.speed = script, speed

    async def frames(self):
        dt = N / 16000 / self.speed
        for item in self.script + [("silence", 999)]:
            n = int(item[-1] * 16000 / N)
            for _ in range(n):
                await asyncio.sleep(dt)
                f = np.zeros(N, np.int16)
                if item[0] == "speech":
                    f[:] = 8000
                    f[0] = hash(item[1]) % 30000
                yield f


class FakeVAD:
    def __call__(self, frame):
        return 0.95 if frame[1] == 8000 else 0.0


class FakeSTT(SpeechToText):
    name = "fake"

    def __init__(self, script):
        self.by_hash = {hash(t) % 30000: t for kind, *rest in script if kind == "speech" for t in [rest[0]]}

    def transcribe(self, pcm):
        a = np.frombuffer(pcm, np.int16)
        for i in range(0, len(a), N):
            if a[i] in self.by_hash and a[i + 1] == 8000:
                return self.by_hash[a[i]]
        return ""


class SlowBrain(Brain):
    name = "slow"

    def __init__(self, cfg):
        super().__init__(cfg, "")
        self.cancelled = 0

    async def stream(self, history, text):
        try:
            for i in range(200):
                await asyncio.sleep(0.01)
                yield f"Sentence number {i}. "
        except asyncio.CancelledError:
            self.cancelled += 1
            raise


def cfg(**kw):
    c = ConvConfig(brain="echo", stt="fake", tts="tone")
    c.silence_timeout_s = kw.pop("timeout", 0.6)      # wall-clock seconds (the script runs at 20x)
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def run(script, brain=None, player=None, **kw):
    c = cfg(**kw)
    s = ConversationSession(c, brain or EchoBrain(c, ""), FakeSTT(script), ToneTTS(), source=ScriptSource(script),
                            player=player or NullPlayer(), vad=FakeVAD())
    reason = asyncio.run(asyncio.wait_for(s.run(greeting=None), 20))
    return s, reason


def test_turn_then_stop_conversation():
    script = [("silence", 0.5), ("speech", "hello there", 1.0), ("silence", 2.0),
              ("speech", "stop conversation", 1.0), ("silence", 2.0)]
    s, reason = run(script)
    assert reason == "user"
    assert s.transcripts == ["hello there", "stop conversation"]
    assert s.history[0] == {"role": "user", "content": "hello there"}
    assert "You said hello there" in s.history[1]["content"]
    assert s.latencies and s.latencies[0]["first_audio_out"] > 0


def test_silence_timeout_exits():
    s, reason = run([("silence", 1.0)], timeout=0.3)
    assert reason == "silence"


def test_barge_in_cancels_reply_and_listens():
    c = cfg()
    brain = SlowBrain(c)
    script = [("speech", "tell me a long story", 1.0), ("silence", 1.5),
              ("speech", "actually goodbye", 1.0), ("silence", 2.0)]
    s, reason = run(script, brain=brain, player=NullPlayer(realtime=True))
    assert reason == "user"
    assert brain.cancelled == 1
    assert s.transcripts[-1] == "actually goodbye"
    assert s.history[1]["content"].endswith("—") or "interrupted" in s.history[1]["content"]


def test_history_is_trimmed():
    script = []
    for i in range(6):
        script += [("speech", f"message {i}", 0.6), ("silence", 1.2)]
    script += [("speech", "goodbye", 0.6)]
    s, _ = run(script, max_turns=2)
    assert len(s.history) <= 4
    assert s.history[-2]["content"] == "message 5"
