"""Pluggable STT and TTS for conversation mode.

STT providers take a finished utterance (16 kHz mono int16 PCM) and return text. A streaming provider such
as Deepgram can implement the same interface later (transcribe the utterance it has been fed).
TTS providers turn one sentence into (float32 mono samples, sample rate) for the playback queue.
"""
from __future__ import annotations

import asyncio
import io
import os
import wave
from abc import ABC, abstractmethod

import numpy as np

from .config import ConvConfig

RATE = 16000


# ---------------------------------------------------------------- speech to text
class SpeechToText(ABC):
    name = "stt"

    @abstractmethod
    def transcribe(self, pcm: bytes) -> str: ...

    def warm(self) -> None: ...


class WhisperSTT(SpeechToText):
    name = "faster-whisper"

    def __init__(self, cfg: ConvConfig):
        self.cfg, self.model = cfg, None

    def warm(self):
        if self.model is not None:
            return
        from faster_whisper import WhisperModel
        device = self.cfg.whisper_device
        if device == "auto":
            try:
                import ctranslate2
                device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
            except Exception:
                device = "cpu"
        compute = "float16" if device == "cuda" else "int8"
        self.model = WhisperModel(self.cfg.whisper_model, device=device, compute_type=compute,
                                  cpu_threads=min(8, os.cpu_count() or 4))
        print(f"[conv] whisper {self.cfg.whisper_model} on {device} ({compute})")

    def transcribe(self, pcm):
        self.warm()
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        peak = float(np.abs(audio).max()) if audio.size else 0.0
        if peak > 0:
            audio = audio * min(0.9 / peak, 30.0)      # the headset mic is quiet
        segs, _ = self.model.transcribe(audio, language="en", beam_size=1, vad_filter=False,
                                        condition_on_previous_text=False, without_timestamps=True,
                                        initial_prompt="Jarvis, Claude.")
        return " ".join(s.text.strip() for s in segs).strip()


class LegacySTT(SpeechToText):
    """The recognizer the rest of JARVIS uses (Google, or Wispr Flow with a key)."""
    name = "google"

    def __init__(self):
        from ..voice.stt import make_stt
        self.inner = make_stt()

    def transcribe(self, pcm):
        return self.inner.transcribe(pcm)


def make_stt(cfg: ConvConfig) -> SpeechToText:
    if cfg.stt.lower() in ("whisper", "faster-whisper", "faster_whisper"):
        try:
            import faster_whisper  # noqa: F401
            return WhisperSTT(cfg)
        except ImportError:
            print("[conv] faster-whisper not installed; using the Google recognizer")
    return LegacySTT()


# ---------------------------------------------------------------- text to speech
class TextToSpeech(ABC):
    name = "tts"

    @abstractmethod
    async def synth(self, text: str) -> tuple[np.ndarray, int]: ...


def _decode_mp3(data: bytes) -> tuple[np.ndarray, int]:
    import miniaudio
    d = miniaudio.decode(data, output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1, sample_rate=24000)
    return np.frombuffer(d.samples, dtype=np.int16).astype(np.float32) / 32768.0, d.sample_rate


class EdgeTTS(TextToSpeech):
    name = "edge"

    def __init__(self, voice: str):
        self.voice = voice

    async def synth(self, text):
        import edge_tts
        buf = bytearray()
        async for chunk in edge_tts.Communicate(text, self.voice, rate="+8%").stream():
            if chunk["type"] == "audio":
                buf += chunk["data"]
        if not buf:
            return np.zeros(0, np.float32), 24000
        return _decode_mp3(bytes(buf))


class PiperTTS(TextToSpeech):
    name = "piper"

    def __init__(self, model_path: str):
        if not model_path or not os.path.exists(model_path):
            raise RuntimeError("CONV_TTS=piper needs CONV_PIPER_MODEL=<path to a Piper .onnx voice>")
        from piper import PiperVoice
        self.voice = PiperVoice.load(model_path)
        self._run("Ready.")                       # first call loads the model; do it now, not mid-reply

    def _run(self, text):
        bio = io.BytesIO()
        with wave.open(bio, "wb") as w:
            if hasattr(self.voice, "synthesize_wav"):     # piper-tts >= 1.3
                self.voice.synthesize_wav(text, w)
            else:
                self.voice.synthesize(text, w)
        bio.seek(0)
        with wave.open(bio, "rb") as r:
            rate, frames = r.getframerate(), r.readframes(r.getnframes())
        return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0, rate

    async def synth(self, text):
        return await asyncio.to_thread(self._run, text)


class ElevenLabsTTS(TextToSpeech):
    name = "elevenlabs"

    def __init__(self, cfg: ConvConfig):
        if not cfg.elevenlabs_key:
            raise RuntimeError("CONV_TTS=elevenlabs needs ELEVENLABS_API_KEY")
        self.cfg = cfg

    async def synth(self, text):
        import aiohttp
        url = (f"https://api.elevenlabs.io/v1/text-to-speech/{self.cfg.elevenlabs_voice}/stream"
               "?output_format=pcm_22050&optimize_streaming_latency=3")
        async with aiohttp.ClientSession() as http:
            async with http.post(url, json={"text": text, "model_id": self.cfg.elevenlabs_model},
                                 headers={"xi-api-key": self.cfg.elevenlabs_key}) as r:
                if r.status != 200:
                    raise RuntimeError(f"ElevenLabs HTTP {r.status}: {(await r.text())[:200]}")
                data = await r.read()
        return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0, 22050


class ToneTTS(TextToSpeech):
    """Test TTS: a short beep per sentence, no network."""
    name = "tone"

    async def synth(self, text):
        t = np.arange(int(0.15 * 16000)) / 16000
        return (0.1 * np.sin(2 * np.pi * 440 * t)).astype(np.float32), 16000


def make_tts(cfg: ConvConfig, default_voice: str) -> TextToSpeech:
    kind = cfg.tts.lower()
    if kind == "auto":
        kind = "piper" if cfg.piper_model and os.path.exists(cfg.piper_model) else "edge"
    try:
        if kind == "piper":
            return PiperTTS(cfg.piper_model)
        if kind == "elevenlabs":
            return ElevenLabsTTS(cfg)
        if kind == "tone":
            return ToneTTS()
    except Exception as e:
        print(f"[conv] {kind} TTS unavailable ({e}); using edge-tts")
    return EdgeTTS(cfg.voice or default_voice)
