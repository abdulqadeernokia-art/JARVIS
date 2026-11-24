"""Conversation-mode settings. Read from the environment / .env (loaded by jarvis_os.config).

Every value has a working default, so .env only needs the lines you want to change. See .env.example.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PIPER_DEFAULT = Path(__file__).resolve().parents[2] / "data" / "models" / "piper" / "en_GB-alan-medium.onnx"


def _env(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


def _f(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


@dataclass
class ConvConfig:
    # brain: claude (Agent SDK, your Claude.ai login) | claude_api (needs a key) | ollama (local)
    brain: str = field(default_factory=lambda: _env("CONV_BRAIN", "claude"))
    claude_model: str = field(default_factory=lambda: _env("CONV_CLAUDE_MODEL", "claude-haiku-5-5"))
    claude_api_key: str = field(default_factory=lambda: _env("JARVIS_CLAUDE_API_KEY", ""))
    ollama_url: str = field(default_factory=lambda: _env("CONV_OLLAMA_URL", "http://127.0.0.1:11434"))
    ollama_model: str = field(default_factory=lambda: _env("CONV_OLLAMA_MODEL", "qwen3.5:2b"))
    max_turns: int = field(default_factory=lambda: int(_f("CONV_MAX_TURNS", 12)))   # user+assistant pairs kept

    # speech to text: whisper (faster-whisper, local) | google (the existing recognizer)
    stt: str = field(default_factory=lambda: _env("CONV_STT", "whisper"))
    whisper_model: str = field(default_factory=lambda: _env("CONV_WHISPER_MODEL", "base.en"))
    whisper_device: str = field(default_factory=lambda: _env("CONV_WHISPER_DEVICE", "auto"))  # auto | cpu | cuda

    # text to speech: auto (piper if its voice is downloaded, else edge) | piper (local, fastest)
    #                 | edge (neural, online, ~1-2 s per sentence) | elevenlabs (cloud)
    tts: str = field(default_factory=lambda: _env("CONV_TTS", "auto"))
    voice: str = field(default_factory=lambda: _env("CONV_VOICE", ""))   # "" = the JARVIS voice setting
    piper_model: str = field(default_factory=lambda: _env(
        "CONV_PIPER_MODEL", str(PIPER_DEFAULT)))  # path to *.onnx voice
    elevenlabs_key: str = field(default_factory=lambda: _env("ELEVENLABS_API_KEY", ""))
    elevenlabs_voice: str = field(default_factory=lambda: _env("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb"))
    elevenlabs_model: str = field(default_factory=lambda: _env("ELEVENLABS_MODEL", "eleven_flash_v2_5"))

    # voice activity detection
    frame_ms: int = 32                       # Silero wants 512 samples at 16 kHz
    end_silence_ms: int = field(default_factory=lambda: int(_f("CONV_END_SILENCE_MS", 700)))
    vad_threshold: float = field(default_factory=lambda: _f("CONV_VAD_THRESHOLD", 0.5))
    vad_threshold_speaking: float = field(default_factory=lambda: _f("CONV_VAD_THRESHOLD_SPEAKING", 0.85))
    min_speech_ms: int = field(default_factory=lambda: int(_f("CONV_MIN_SPEECH_MS", 130)))
    barge_in_ms: int = field(default_factory=lambda: int(_f("CONV_BARGE_IN_MS", 260)))
    speculative_ms: int = field(default_factory=lambda: int(_f("CONV_SPECULATIVE_STT_MS", 250)))  # 0 = off
    preroll_ms: int = 320
    max_utterance_s: float = 30.0
    silence_timeout_s: float = field(default_factory=lambda: _f("CONV_SILENCE_TIMEOUT", 30))

    @property
    def frame_samples(self) -> int:
        return 16000 * self.frame_ms // 1000
