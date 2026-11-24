"""Model providers behind one interface. See MODEL_ROUTING.md.

The main agent runs on Claude through the Claude Agent SDK (your Claude.ai login). These providers are used
for one-shot work: independent second opinions, cross-checks, summaries.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod


class ModelProvider(ABC):
    name: str

    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    async def complete(self, prompt: str, system: str = "", model: str | None = None) -> tuple[str, str]:
        """Returns (text, exact model label used)."""


class ClaudeProvider(ModelProvider):
    """One-shot Claude call via the Agent SDK, with no tools: an independent opinion."""
    name = "claude"

    def __init__(self, default_model: str = "opus"):
        self.default_model = default_model

    def available(self) -> bool:
        return True

    async def complete(self, prompt, system="", model=None):
        from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query
        model = model or self.default_model
        opts = ClaudeAgentOptions(system_prompt=system or "You are a careful, independent analyst.",
                                  model=model, tools=[], setting_sources=[], max_turns=1,
                                  permission_mode="dontAsk")
        parts, used = [], model
        async for msg in query(prompt=prompt, options=opts):
            if isinstance(msg, AssistantMessage):
                used = getattr(msg, "model", None) or used
                parts += [b.text for b in msg.content if isinstance(b, TextBlock)]
        return "\n".join(parts).strip(), f"Claude ({used})"


class OpenAIProvider(ModelProvider):
    """Enabled when OPENAI_API_KEY is set and the `openai` package is installed."""
    name = "openai"

    def __init__(self, default_model: str | None = None):
        self.default_model = default_model or os.getenv("OPENAI_MODEL", "gpt-4o")

    def available(self) -> bool:
        if not os.getenv("OPENAI_API_KEY"):
            return False
        try:
            import openai  # noqa: F401
            return True
        except ImportError:
            return False

    async def complete(self, prompt, system="", model=None):
        from openai import AsyncOpenAI
        model = model or self.default_model
        client = AsyncOpenAI()
        r = await client.chat.completions.create(model=model, messages=[
            {"role": "system", "content": system or "You are a careful, independent analyst."},
            {"role": "user", "content": prompt}])
        return r.choices[0].message.content or "", f"OpenAI ({r.model})"


class MockProvider(ModelProvider):
    def __init__(self, name: str = "mock", reply: str = "mock answer"):
        self.name, self.reply = name, reply

    def available(self) -> bool:
        return True

    async def complete(self, prompt, system="", model=None):
        return f"{self.reply}: {prompt[:60]}", f"Mock ({self.name})"


def default_providers(settings) -> dict[str, ModelProvider]:
    return {"claude": ClaudeProvider(settings.model_reasoning), "openai": OpenAIProvider()}
