"""Latency test: time from the end of your speech to the first audio out. Target < 1.5 s.

  python -m jarvis_os.conversation.latency_test            synthetic: a recorded question is fed in as the mic
  python -m jarvis_os.conversation.latency_test --live     talk into your mic; reports each turn (Ctrl+C to end)
  ... --brain ollama|claude|claude_api  --tts edge|piper|elevenlabs  --stt whisper|google  --runs 3
"""
from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import sys

import numpy as np


async def synthetic(parts, runs: int) -> list[float]:
    from .audio import ArraySource
    from .session import ConversationSession
    questions = ["What is the capital of France?", "Give me one fun fact about the moon.",
                 "How are you today?"]
    out = []
    for i in range(runs):
        samples, rate = await parts.tts.synth(questions[i % len(questions)])
        pcm = np.interp(np.linspace(0, len(samples) - 1, int(len(samples) * 16000 / rate)),
                        np.arange(len(samples)), samples)
        src = ArraySource((pcm * 32767 * 0.6).astype(np.int16))
        s = ConversationSession(parts.cfg, parts.brain, parts.stt, parts.tts, source=src, history=parts.history)
        run = asyncio.create_task(s.run(greeting=None))
        while not s.latencies and not run.done():
            await asyncio.sleep(0.05)
        await asyncio.sleep(1.0)
        s.stop("test")
        await run
        if s.latencies:
            out.append(s.latencies[0]["first_audio_out"])
    return out


async def live(parts) -> list[float]:
    from .session import ConversationSession
    s = ConversationSession(parts.cfg, parts.brain, parts.stt, parts.tts, history=parts.history)
    print("Talk normally. Say 'stop conversation' or press Ctrl+C to finish.\n")
    try:
        await s.run(greeting="Latency test. Say something.")
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    return [x["first_audio_out"] for x in s.latencies]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--live", action="store_true")
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--brain"); p.add_argument("--tts"); p.add_argument("--stt")
    a = p.parse_args()
    for k in ("brain", "tts", "stt"):
        if getattr(a, k):
            os.environ[f"CONV_{k.upper()}"] = getattr(a, k)
    try:
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    except Exception:
        pass
    from .. import config
    from ..core import secrets
    secrets.export_env()
    from . import build

    async def go():
        parts = build(config.Settings.load())
        try:
            return await (live(parts) if a.live else synthetic(parts, a.runs))
        finally:
            await parts.brain.close()

    res = asyncio.run(go())
    print("\n==== speech end → first audio out ====")
    for i, r in enumerate(res, 1):
        print(f"  turn {i}: {r * 1000:.0f} ms {'PASS' if r < 1.5 else 'over target'}")
    if res:
        print(f"  median {statistics.median(res) * 1000:.0f} ms (target < 1500 ms)")
    else:
        print("  no turns measured")


if __name__ == "__main__":
    main()
