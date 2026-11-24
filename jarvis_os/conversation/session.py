"""Hands-free conversation session.

  capture ─▶ VAD ─▶ STT ─▶ LLM (streamed) ─▶ sentence chunker ─▶ TTS ─▶ playback
     ▲         │ barge-in: user speaks while JARVIS thinks/talks → stop playback, clear queues, cancel LLM
     └─────────┘

Each stage is an asyncio task connected by queues. Every queued item carries the "generation" it belongs
to; a barge-in bumps the generation so anything still in flight from the old reply is dropped.
Exit: "stop conversation" / "goodbye", or 30 s without anyone speaking.
"""
from __future__ import annotations

import asyncio
import collections
import contextlib
import datetime as dt
import enum
import re
import time

import numpy as np

from ..agent.orchestrator import SentenceStream
from .audio import RATE, MicSource, Player, SileroVAD
from .brains import Brain
from .config import ConvConfig
from .speech import SpeechToText, TextToSpeech

EXIT = re.compile(r"\b(stop (the |this )?conversation|end (the |this )?conversation|exit conversation( mode)?|"
                  r"good ?bye|bye(,)? jarvis|that'?s all for now|talk (to you )?later)\b", re.I)
GOODBYES = {"user": "Talk to you later.", "silence": "I'll leave you to it. Say Jarvis when you need me."}


class State(enum.Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    INTERRUPTED = "interrupted"


class FirstChunkStream(SentenceStream):
    """Sentence chunker that lets the very first phrase go early (at a comma after a few words), so the
    voice starts before the first full sentence has been generated."""
    _FIRST = re.compile(r"^(.{18,}?[,;:—])\s")

    def __init__(self, emit):
        super().__init__(emit)
        self.first = True

    def feed(self, delta: str) -> None:
        if self.first:
            self.buf += delta
            m = self._FIRST.match(self.buf)
            if m and len(m.group(1).split()) >= 4 and not _SENT.search(m.group(1)):
                self.first = False
                self._out(m.group(1))
                self.buf = self.buf[m.end():]
                return
            if _SENT.search(self.buf):
                self.first = False
            delta, self.buf = self.buf, ""
        super().feed(delta)


_SENT = re.compile(r"[.!?]\s")


def log(stage: str, msg: str) -> None:
    print(f"[conv {dt.datetime.now():%H:%M:%S.%f}"[:-3] + f"] {stage:<6} {msg}")


class ConversationSession:
    def __init__(self, cfg: ConvConfig, brain: Brain, stt: SpeechToText, tts: TextToSpeech, bus=None,
                 source=None, player=None, history: list | None = None, vad=None):
        self.cfg, self.brain, self.stt, self.tts, self.bus = cfg, brain, stt, tts, bus
        self.source = source or MicSource(cfg.frame_samples)
        self.player = player
        self.vad = vad or SileroVAD()
        self.history: list[dict] = history if history is not None else []
        self.state = State.IDLE
        self.gen = 0
        self.mic_level = 0.0
        self.latencies: list[dict] = []
        self.transcripts: list[str] = []
        self.exit_reason: str | None = None
        self._stop = asyncio.Event()
        self._peak = 300.0
        self._reply_task: asyncio.Task | None = None
        self._turn_spoken: list[str] = []
        self._turn_entry: dict | None = None
        self._timing: dict = {}
        self._last_activity = time.monotonic()
        self._in_speech = False
        self.utt_q: asyncio.Queue = asyncio.Queue()
        self.text_q: asyncio.Queue = asyncio.Queue()
        self.sent_q: asyncio.Queue = asyncio.Queue()
        self.audio_q: asyncio.Queue = asyncio.Queue()
        self.loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------ public
    @property
    def speech_level(self) -> float:
        return float(getattr(self.player, "level", 0.0) or 0.0)

    def stop(self, reason: str = "user") -> None:
        """Thread-safe."""
        def _set():
            self.exit_reason = self.exit_reason or reason
            self._stop.set()
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(_set)
        else:
            _set()

    async def run(self, greeting: str | None = "I'm listening.") -> str:
        self.loop = asyncio.get_running_loop()
        if self.player is None:
            self.player = await asyncio.to_thread(Player)
        await asyncio.gather(asyncio.to_thread(self.stt.warm), self._safe_warm())
        self._publish("conversation", on=True)
        log("start", f"brain={self.brain.name} stt={self.stt.name} tts={self.tts.name} "
                     f"end_silence={self.cfg.end_silence_ms}ms timeout={self.cfg.silence_timeout_s:.0f}s")
        tasks = [asyncio.create_task(c, name=n) for n, c in [
            ("vad", self._vad_task()), ("stt", self._stt_task()), ("llm", self._llm_task()),
            ("tts", self._tts_task()), ("play", self._play_task()), ("timeout", self._timeout_task())]]
        self._set_state(State.LISTENING)
        if greeting:
            self._enqueue_say(greeting)
        try:
            done, _ = await asyncio.wait([asyncio.create_task(self._stop.wait()), *tasks],
                                         return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                if t in tasks and t.exception():
                    log("error", f"{t.get_name()} failed: {t.exception()!r}")
                    self.exit_reason = self.exit_reason or "error"
        finally:
            self.gen += 1
            if self._reply_task:
                self._reply_task.cancel()
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, *( [self._reply_task] if self._reply_task else []),
                                 return_exceptions=True)
            reason = self.exit_reason or "user"
            if reason in GOODBYES:
                await self._say_now(GOODBYES[reason])
            self._set_state(State.IDLE)
            self._publish("conversation", on=False, reason=reason)
            log("end", f"reason={reason}")
        return self.exit_reason or "user"

    # ------------------------------------------------------------ helpers
    async def _safe_warm(self):
        try:
            await self.brain.warm()
        except Exception as e:
            log("llm", f"warm-up failed: {e!r}")

    def _publish(self, event: str, **data) -> None:
        if self.bus:
            self.bus.publish(event, **data)

    def _set_state(self, s: State) -> None:
        if s is self.state:
            return
        self.state = s
        ui = {State.IDLE: "idle", State.LISTENING: "listening", State.THINKING: "transcribing",
              State.SPEAKING: None, State.INTERRUPTED: "listening"}[s]
        if ui:
            self._publish("voice.state", state=ui)
        if s is State.THINKING:
            self._publish("agent.thinking", route="conversation", model=self.brain.name)

    def _enqueue_say(self, text: str) -> None:
        for s in re.split(r"(?<=[.!?])\s+", text):
            if s.strip():
                self.sent_q.put_nowait((self.gen, s.strip()))
        self.sent_q.put_nowait((self.gen, None))

    async def _say_now(self, text: str) -> None:
        try:
            samples, rate = await asyncio.wait_for(self.tts.synth(text), 6)
            self._publish("speaker", speaking=True, text=text)
            await asyncio.to_thread(self.player.play, samples, rate, lambda: True)
        except Exception as e:
            log("tts", f"goodbye failed: {e!r}")
        finally:
            self._publish("speaker", speaking=False, text="")

    @staticmethod
    def _drain(q: asyncio.Queue) -> None:
        while not q.empty():
            q.get_nowait()

    def barge_in(self) -> None:
        """User started talking over JARVIS: silence him and forget the rest of his reply at once."""
        t0 = time.monotonic()
        self._set_state(State.INTERRUPTED)
        self.gen += 1
        if self._reply_task and not self._reply_task.done():
            self._reply_task.cancel()
        for q in (self.text_q, self.sent_q, self.audio_q):
            self._drain(q)
        if self._turn_entry is not None:                # reply not fully heard: remember only what was said
            said = " ".join(self._turn_spoken)
            self._turn_entry["content"] = (said + " —").strip() if said else "(interrupted before speaking)"
        self._turn_entry = None
        self._publish("speaker", speaking=False, text="")
        self._publish("agent.cancelled", reason="barge-in")
        log("barge", f"interrupted in {1000 * (time.monotonic() - t0):.0f} ms")

    # ------------------------------------------------------------ stages
    async def _vad_task(self):
        cfg = self.cfg
        fm = cfg.frame_ms
        preroll = collections.deque(maxlen=max(1, cfg.preroll_ms // fm))
        utt: list[np.ndarray] = []
        in_speech, voiced_run, silence, last_voice = False, 0, 0, 0.0
        spec = None      # speculative transcription started during the end-of-turn silence
        async for frame in self.source.frames():
            if self._stop.is_set():
                return
            rms = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)))
            self._peak = max(rms, self._peak * 0.995, 30.0)
            self.mic_level = min(1.0, rms / self._peak)
            p = self.vad(frame)
            if not in_speech:
                preroll.append(frame)
                talking = self.state in (State.SPEAKING,)
                thr = cfg.vad_threshold_speaking if talking else cfg.vad_threshold
                need = cfg.barge_in_ms if talking else cfg.min_speech_ms
                voiced_run = voiced_run + fm if p >= thr else 0
                if voiced_run >= need:
                    if self.state in (State.THINKING, State.SPEAKING):
                        self.barge_in()
                    in_speech, silence, last_voice = True, 0, time.monotonic()
                    self._in_speech = True
                    utt = list(preroll)
                    preroll.clear()
                    self._last_activity = time.monotonic()
                    self._set_state(State.LISTENING)
                    log("vad", f"speech start (p={p:.2f})")
                continue
            utt.append(frame)
            self._last_activity = time.monotonic()
            if p >= cfg.vad_threshold - 0.15:
                silence, last_voice = 0, time.monotonic()
                spec = None                      # they kept talking: that guess is stale
            else:
                silence += fm
                if spec is None and cfg.speculative_ms and silence >= cfg.speculative_ms:
                    # start transcribing now; if they stay quiet until end_silence_ms we already have it
                    pcm_now = np.concatenate(utt).astype(np.int16).tobytes()
                    spec = asyncio.ensure_future(asyncio.to_thread(self.stt.transcribe, pcm_now))
            if silence >= cfg.end_silence_ms or len(utt) * fm / 1000 >= cfg.max_utterance_s:
                in_speech, voiced_run = False, 0
                self._in_speech = False
                now = time.monotonic()
                pcm = np.concatenate(utt).astype(np.int16).tobytes()
                log("vad", f"speech end ({len(utt) * fm / 1000:.1f}s audio)")
                self._last_activity = now
                self._set_state(State.THINKING)
                await self.utt_q.put((self.gen, pcm, {"speech_end": last_voice, "detected": now}, spec))
                utt, spec = [], None

    async def _stt_task(self):
        while True:
            gen, pcm, timing, spec = await self.utt_q.get()
            t0 = time.monotonic()
            try:
                text = (await (spec if spec is not None else asyncio.to_thread(self.stt.transcribe, pcm))).strip()
            except Exception as e:
                log("stt", f"failed: {e!r}")
                text = ""
            timing["stt"] = time.monotonic()
            log("stt", f"{1000 * (timing['stt'] - t0):.0f} ms{' (speculative)' if spec else ''}: {text!r}")
            if gen != self.gen:
                continue
            if not re.search(r"[a-z0-9]", text, re.I):
                if self.state is State.THINKING:
                    self._set_state(State.LISTENING)
                continue
            self._publish("voice.transcript", text=text, partial=False)
            self.transcripts.append(text)
            if EXIT.search(text):
                self.stop("user")
                return
            await self.text_q.put((gen, text, timing))

    async def _llm_task(self):
        while True:
            gen, text, timing = await self.text_q.get()
            if gen != self.gen:
                continue
            if self._reply_task and not self._reply_task.done():
                self._reply_task.cancel()
            self._reply_task = asyncio.create_task(self._reply(gen, text, timing))

    async def _reply(self, gen: int, text: str, timing: dict):
        prior = self.history[-2 * self.cfg.max_turns:]
        self.history.append({"role": "user", "content": text})
        entry = {"role": "assistant", "content": ""}
        self.history.append(entry)
        self._turn_entry, self._turn_spoken, self._timing = entry, [], timing
        parts: list[str] = []

        def emit(sentence: str):
            if "first_sentence" not in timing:
                timing["first_sentence"] = time.monotonic()
            self.sent_q.put_nowait((gen, sentence))

        chunker = FirstChunkStream(emit)
        try:
            async with contextlib.aclosing(self.brain.stream(prior, text)) as stream:
                async for delta in stream:
                    if "first_token" not in timing:
                        timing["first_token"] = time.monotonic()
                        log("llm", f"first token {1000 * (timing['first_token'] - timing['stt']):.0f} ms after STT")
                    parts.append(delta)
                    chunker.feed(re.sub(r"[*_#`]+", "", delta))
            chunker.flush()
        except asyncio.CancelledError:
            log("llm", "cancelled")
            raise
        except Exception as e:
            log("llm", f"failed: {e!r}")
            if not parts:
                emit("Sorry, I lost my train of thought there.")
        full = "".join(parts).strip()
        entry["content"] = full or "(no reply)"
        del self.history[:-2 * self.cfg.max_turns]          # rolling memory: last N turns
        if gen == self.gen:
            self.sent_q.put_nowait((gen, None))             # end of this reply

    async def _tts_task(self):
        while True:
            gen, sentence = await self.sent_q.get()
            if gen != self.gen:
                continue
            if sentence is None:
                await self.audio_q.put((gen, None, 0, None))
                continue
            t0 = time.monotonic()
            try:
                samples, rate = await self.tts.synth(sentence)
            except Exception as e:
                log("tts", f"failed: {e!r}")
                continue
            if gen != self.gen:
                continue
            if self._timing.get("stt") and "first_audio_ready" not in self._timing:
                self._timing["first_audio_ready"] = time.monotonic()
            log("tts", f"{1000 * (time.monotonic() - t0):.0f} ms for {sentence[:50]!r}")
            await self.audio_q.put((gen, samples, rate, sentence))

    async def _play_task(self):
        while True:
            gen, samples, rate, sentence = await self.audio_q.get()
            if gen != self.gen:
                continue
            if samples is None:                              # reply finished playing
                self._publish("speaker", speaking=False, text="")
                self._turn_entry = None
                if self.state in (State.SPEAKING, State.THINKING):
                    self._set_state(State.LISTENING)
                self._last_activity = time.monotonic()
                continue
            timing = self._timing

            def started(timing=timing):
                if timing.get("stt") and "first_audio_out" not in timing:
                    timing["first_audio_out"] = time.monotonic() + self.player.output_latency
                    self._report(timing)

            self._set_state(State.SPEAKING)
            self._publish("speaker", speaking=True, text=sentence)
            ok = await asyncio.to_thread(self.player.play, samples, rate, lambda g=gen: g == self.gen, started)
            if ok and gen == self.gen:
                self._turn_spoken.append(sentence)
            self._last_activity = time.monotonic()

    async def _timeout_task(self):
        while True:
            await asyncio.sleep(0.25)
            idle = time.monotonic() - self._last_activity
            if self.state is State.LISTENING and not self._in_speech and self.utt_q.empty() and idle >= self.cfg.silence_timeout_s:
                log("idle", f"{idle:.0f}s of silence")
                self.stop("silence")
                return

    def _report(self, t: dict) -> None:
        end = t["speech_end"]

        def ms(k):
            return f"{1000 * (t[k] - end):.0f}" if k in t else "-"
        total = t["first_audio_out"] - end
        self.latencies.append({k: v - end for k, v in t.items()})
        log("lat", f"speech end → detected {ms('detected')} · stt {ms('stt')} · first token {ms('first_token')} · "
                   f"first sentence {ms('first_sentence')} · audio ready {ms('first_audio_ready')} · "
                   f"FIRST AUDIO OUT {1000 * total:.0f} ms {'✓' if total < 1.5 else '(target 1500)'}")
