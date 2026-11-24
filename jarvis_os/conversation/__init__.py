"""Hands-free conversation mode: talk naturally back and forth until "stop conversation" or 30 s of silence."""
from __future__ import annotations

from .brains import Brain, make_brain, system_prompt
from .config import ConvConfig
from .session import EXIT, ConversationSession, State
from .speech import make_stt, make_tts

__all__ = ["Brain", "ConvConfig", "ConversationSession", "EXIT", "State", "build", "make_brain", "make_stt",
           "make_tts", "system_prompt"]


class Parts:
    """Brain, STT and TTS built once and reused, so the second conversation starts instantly."""

    def __init__(self, cfg: ConvConfig, settings=None):
        user = getattr(settings, "user_name", "sir")
        personality = getattr(settings, "personality", "calm, dry British wit, concise")
        self.cfg = cfg
        self.brain = make_brain(cfg, system_prompt(user, personality))
        self.stt = make_stt(cfg)
        self.tts = make_tts(cfg, getattr(settings, "voice", "en-GB-RyanNeural"))
        self.history: list[dict] = []


def build(settings=None, cfg: ConvConfig | None = None) -> Parts:
    return Parts(cfg or ConvConfig(), settings)
