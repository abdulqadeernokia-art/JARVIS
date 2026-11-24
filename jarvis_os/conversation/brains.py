"""Swappable conversation brains. One interface: stream(history, user_text) -> async iterator of text deltas.

  ClaudeSDKBrain  Claude through the Agent SDK (your Claude.ai login, no key). Default.
  ClaudeAPIBrain  Claude Messages API (needs JARVIS_CLAUDE_API_KEY). Lowest latency.
  OllamaBrain     Local model through Ollama (e.g. qwen3.5:2b). Works offline.

Cancelling the consuming task stops the stream; each brain cleans up its own connection.
"""
from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from typing import AsyncIterator

from .config import ConvConfig

Turn = dict  # {"role": "user"|"assistant", "content": str}


def system_prompt(user_name: str = "sir", personality: str = "calm, dry British wit, concise") -> str:
    return (f"You are JARVIS, a personal AI assistant, in a live spoken conversation with {user_name}. "
            f"Personality: {personality}. Everything you write is read aloud by a speech synthesiser, so: "
            "reply in one to three short sentences unless asked for more; plain spoken English only; "
            "no markdown, no lists, no headings, no emoji, no code; spell out symbols. "
            "If you are interrupted, just answer the new thing. Ask a short question back when it keeps the "
            "conversation natural. You cannot use tools in this mode; if asked to act on the computer, say "
            "they can say 'stop conversation' and ask you normally.")


class Brain(ABC):
    name = "brain"

    def __init__(self, cfg: ConvConfig, system: str):
        self.cfg, self.system = cfg, system

    @abstractmethod
    def stream(self, history: list[Turn], user_text: str) -> AsyncIterator[str]: ...

    async def warm(self) -> None:
        """Optional: open connections early so the first reply is fast."""

    async def close(self) -> None: ...


class OllamaBrain(Brain):
    name = "ollama"

    async def warm(self):
        """Load the model into memory now (the first load takes seconds) and keep it there."""
        import aiohttp
        async with aiohttp.ClientSession() as http:
            async with http.post(f"{self.cfg.ollama_url}/api/generate",
                                 json={"model": self.cfg.ollama_model, "keep_alive": "30m"},
                                 timeout=aiohttp.ClientTimeout(total=60)) as r:
                await r.read()

    async def stream(self, history, user_text):
        import aiohttp
        body = {"model": self.cfg.ollama_model, "stream": True, "think": False, "keep_alive": "30m",
                "options": {"num_predict": 220, "temperature": 0.7},
                "messages": [{"role": "system", "content": self.system}, *history,
                             {"role": "user", "content": user_text}]}
        async with aiohttp.ClientSession() as http:
            async with http.post(f"{self.cfg.ollama_url}/api/chat", json=body,
                                 timeout=aiohttp.ClientTimeout(total=120)) as r:
                if r.status != 200:
                    raise RuntimeError(f"Ollama HTTP {r.status}: {(await r.text())[:200]}")
                async for line in r.content:
                    if not line.strip():
                        continue
                    msg = json.loads(line)
                    if delta := msg.get("message", {}).get("content"):
                        yield delta
                    if msg.get("done"):
                        break


class ClaudeAPIBrain(Brain):
    name = "claude_api"
    URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, cfg, system):
        super().__init__(cfg, system)
        if not cfg.claude_api_key:
            raise RuntimeError("CONV_BRAIN=claude_api needs JARVIS_CLAUDE_API_KEY")
        self._http = None

    async def warm(self):
        import aiohttp
        if self._http is None:
            self._http = aiohttp.ClientSession()

    async def stream(self, history, user_text):
        await self.warm()
        body = {"model": self.cfg.claude_model, "max_tokens": 400, "stream": True, "system": self.system,
                "messages": [*history, {"role": "user", "content": user_text}]}
        headers = {"x-api-key": self.cfg.claude_api_key, "anthropic-version": "2023-06-01",
                   "content-type": "application/json"}
        async with self._http.post(self.URL, json=body, headers=headers) as r:
            if r.status != 200:
                raise RuntimeError(f"Claude API HTTP {r.status}: {(await r.text())[:200]}")
            async for raw in r.content:
                line = raw.decode("utf-8", "ignore").strip()
                if not line.startswith("data:"):
                    continue
                ev = json.loads(line[5:])
                if ev.get("type") == "content_block_delta" and ev["delta"].get("type") == "text_delta":
                    yield ev["delta"]["text"]
                elif ev.get("type") == "message_stop":
                    break

    async def close(self):
        if self._http:
            await self._http.close()
            self._http = None


class ClaudeSDKBrain(Brain):
    """Claude via the Agent SDK. Keeps one warm client; the SDK holds the session history, so we only send
    the new message. When the session grows past max_turns we reconnect and seed it with the trimmed history."""
    name = "claude"

    def __init__(self, cfg, system):
        super().__init__(cfg, system)
        self.client = None
        self.turns = 0

    async def warm(self):
        if self.client is None:
            from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

            from ..config import DATA_DIR
            opts = ClaudeAgentOptions(system_prompt=self.system, model=self.cfg.claude_model, tools=[],
                                      allowed_tools=[], permission_mode="dontAsk", setting_sources=[],
                                      include_partial_messages=True, max_turns=1, cwd=str(DATA_DIR))
            self.client = ClaudeSDKClient(options=opts)
            await self.client.connect()
            self.turns = 0

    async def stream(self, history, user_text):
        from claude_agent_sdk import AssistantMessage, ResultMessage, StreamEvent, TextBlock
        if self.client is not None and self.turns >= self.cfg.max_turns:
            await self.close()
        fresh = self.client is None
        await self.warm()
        prompt = user_text
        if fresh and history:
            past = "\n".join(f"{'Me' if t['role'] == 'user' else 'You'}: {t['content']}" for t in history)
            prompt = f"(Our conversation so far:\n{past}\n)\n\n{user_text}"
        self.turns += 1
        streamed = False
        finished = False
        try:
            await self.client.query(prompt)
            async for msg in self.client.receive_response():
                if isinstance(msg, StreamEvent):
                    ev = msg.event
                    if ev.get("type") == "content_block_delta" and ev["delta"].get("type") == "text_delta":
                        streamed = True
                        yield ev["delta"]["text"]
                elif isinstance(msg, AssistantMessage) and not streamed:
                    for b in msg.content:
                        if isinstance(b, TextBlock):
                            yield b.text
                elif isinstance(msg, ResultMessage):
                    finished = True
        finally:
            if not finished and self.client is not None:
                await self._abort()

    async def _abort(self):
        """Interrupted mid-reply: stop Claude and drain the rest so the next turn starts clean."""
        client = self.client
        try:
            await client.interrupt()

            async def drain():
                async for _ in client.receive_response():
                    pass
            await asyncio.wait_for(drain(), 3)
        except BaseException:
            self.client = None          # couldn't drain: start a fresh session next turn
            try:
                await client.disconnect()
            except BaseException:
                pass

    async def close(self):
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass
            self.client = None


class EchoBrain(Brain):
    """Test brain: answers instantly, token by token."""
    name = "echo"

    async def stream(self, history, user_text):
        for w in f"You said {user_text}. Anything else?".split(" "):
            await asyncio.sleep(0.005)
            yield w + " "


def make_brain(cfg: ConvConfig, system: str) -> Brain:
    kind = cfg.brain.lower()
    if kind in ("ollama", "qwen", "local"):
        return OllamaBrain(cfg, system)
    if kind in ("claude_api", "api"):
        return ClaudeAPIBrain(cfg, system)
    if kind == "echo":
        return EchoBrain(cfg, system)
    return ClaudeSDKBrain(cfg, system)
