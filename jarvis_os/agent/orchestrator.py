"""Agent orchestrator: the JARVIS loop.

INPUT -> classify/route -> retrieve context (memories, tasks) -> run Claude with tools -> stream speech
-> trace + provenance -> result.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import re
from abc import ABC, abstractmethod
from typing import Callable

from ..config import DATA_DIR
from ..tasks.store import TaskStore
from ..tools.registry import ToolResult
from . import router
from .prompts import system_prompt

os.environ.pop("ANTHROPIC_API_KEY", None)   # use the Claude.ai login, never a stray API key

SpeakFn = Callable[[str], None]
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")


class SentenceStream:
    """Turns streamed text deltas into whole sentences for low-latency speech."""

    _ENUM = re.compile(r"^(\(?\d{1,2}[.)]|[-*•])$")      # a bare "1." or "-" left by list formatting
    _BULLET = re.compile(r"^\s*([-*•]|\d{1,2}[.)])\s+")

    def __init__(self, emit: SpeakFn):
        self.emit, self.buf, self.carry = emit, "", ""

    def _out(self, sentence: str) -> None:
        s = sentence.strip()
        if not s:
            return
        if self._ENUM.match(s):          # never speak "1." on its own; attach to the next sentence
            self.carry = ""
            return
        s = self._BULLET.sub("", s)
        self.emit(s)

    def feed(self, delta: str) -> None:
        self.buf += delta
        parts = _SENTENCE_END.split(self.buf)
        for sentence in parts[:-1]:
            self._out(sentence)
        self.buf = parts[-1]

    def flush(self) -> None:
        self._out(self.buf)
        self.buf = ""


class Agent(ABC):
    def __init__(self, svc):
        self.svc = svc

    @abstractmethod
    async def run(self, text: str, speak: SpeakFn, channel: str = "voice") -> str: ...

    async def cancel(self) -> None: ...

    async def warm(self) -> None: ...

    async def reset(self) -> None: ...

    async def close(self) -> None: ...

    def build_context(self, text: str) -> str:
        svc = self.svc
        lines = [f"Now: {dt.datetime.now().astimezone():%A %d %B %Y %H:%M %Z}"]
        if svc.privacy:
            lines.append("PRIVACY MODE IS ON: do not store memories; keep things ephemeral.")
        prof = svc.memory.profile(8)
        rel = [m for m in svc.memory.search(text, 6) if m["id"] not in {p["id"] for p in prof}]
        if prof or rel:
            lines.append("Stored memories (cite source if used):")
            lines += [f"- {svc.memory.fmt(m)}" for m in prof + rel]
        soon = [t for t in svc.tasks.open_tasks(10)
                if t["due_at"] and t["due_at"] < dt.datetime.now().timestamp() + 36 * 3600]
        if soon:
            lines.append("Open items due soon:")
            lines += [f"- {TaskStore.fmt(t)}" for t in soon[:6]]
        return "<context>\n" + "\n".join(lines) + "\n</context>"


def _mcp_content(res: ToolResult) -> dict:
    content = [{"type": "text", "text": res.text}]
    if res.image_png_b64:
        content.append({"type": "image", "data": res.image_png_b64, "mimeType": res.image_mime})
    out: dict = {"content": content}
    if res.is_error:
        out["is_error"] = True
    return out


class ClaudeAgent(Agent):
    """Main agent on Claude via the Claude Agent SDK (uses the user's Claude.ai / Claude Code login)."""

    BUILTIN = ["WebSearch", "WebFetch"]

    def __init__(self, svc):
        super().__init__(svc)
        self.client = None
        self.model = None

    def _options(self):
        from claude_agent_sdk import ClaudeAgentOptions, create_sdk_mcp_server, tool
        reg = self.svc.registry
        sdk_tools = []
        for t in reg.tools.values():
            async def handler(args, _name=t.name):
                return _mcp_content(await reg.execute(_name, args))
            sdk_tools.append(tool(t.name, t.description, t.schema())(handler))
        server = create_sdk_mcp_server(name="jarvis", version="1.0.0", tools=sdk_tools)
        return ClaudeAgentOptions(
            system_prompt=system_prompt(self.svc.settings),
            model=self.svc.settings.model_fast,
            mcp_servers={"jarvis": server},
            tools=self.BUILTIN,
            allowed_tools=self.BUILTIN + [f"mcp__jarvis__{n}" for n in reg.tools],
            permission_mode="dontAsk",
            setting_sources=[],             # don't load the user's Claude Code settings / CLAUDE.md
            include_partial_messages=True,  # stream text for low-latency speech
            max_buffer_size=64 * 1024 * 1024,  # screenshots make large messages; default 1 MB crashed the reader
            max_turns=40,
            cwd=str(DATA_DIR),
        )

    async def _ensure(self):
        if self.client is None:
            from claude_agent_sdk import ClaudeSDKClient
            self.client = ClaudeSDKClient(options=self._options())
            await self.client.connect()
            self.model = self.svc.settings.model_fast

    async def run(self, text, speak, channel="voice"):
        from claude_agent_sdk import AssistantMessage, ResultMessage, StreamEvent, TextBlock, ToolUseBlock
        svc = self.svc
        await self._ensure()
        r = router.route(text, svc.settings)
        run_id = svc.tracer.start_run(text, channel)
        svc.tracer.set_route(run_id, r.name, r.model)
        svc.registry.current_run = run_id
        if r.model != self.model:
            await self.client.set_model(r.model)
            self.model = r.model
        svc.bus.publish("agent.thinking", run_id=run_id, route=r.name, model=r.model)

        spoken: list[str] = []

        def emit(sentence: str):
            spoken.append(sentence)
            svc.bus.publish("agent.text", run_id=run_id, text=sentence)
            speak(sentence)

        stream = SentenceStream(emit)
        streamed_this_message = False
        status = "completed"
        try:
            await self.client.query(f"{self.build_context(text)}\n\nUser ({channel}): {text}")
            async for msg in self.client.receive_response():
                if isinstance(msg, StreamEvent):
                    ev = msg.event
                    if ev.get("type") == "message_start":
                        streamed_this_message = False
                    elif ev.get("type") == "content_block_delta" and ev["delta"].get("type") == "text_delta":
                        streamed_this_message = True
                        stream.feed(ev["delta"]["text"])
                    elif ev.get("type") in ("content_block_stop", "message_stop"):
                        stream.flush()
                elif isinstance(msg, AssistantMessage):
                    for b in msg.content:
                        if isinstance(b, TextBlock) and not streamed_this_message and b.text.strip():
                            for s in _SENTENCE_END.split(b.text):
                                if s.strip():
                                    emit(s.strip())
                        elif isinstance(b, ToolUseBlock) and not b.name.startswith("mcp__"):
                            # built-in tools (web search/fetch) don't pass through our registry: trace them here
                            svc.tracer.record(run_id, "tool", b.name, risk="READ", status="ok",
                                              detail={"args": b.input, "sources": [b.input.get("url") or
                                                                                   b.input.get("query", "")]})
                            svc.bus.publish("tool.started", run_id=run_id, tool=b.name,
                                            summary=str(b.input.get("query") or b.input.get("url") or ""))
                elif isinstance(msg, ResultMessage):
                    stream.flush()
                    if msg.is_error:
                        status = "failed"
                        if not spoken:
                            emit("Something went wrong on my end, I'm afraid.")
        except asyncio.CancelledError:
            status = "cancelled"
            raise
        except Exception as e:
            status = "failed"
            emit(f"I ran into a problem: {type(e).__name__}.")
            self.client = None   # reconnect next time
        finally:
            output = " ".join(spoken)
            svc.tracer.end_run(run_id, output, status)
            svc.registry.current_run = None
        return output

    async def warm(self):
        try:
            await self._ensure()
        except Exception as e:
            print(f"[agent] warm-up failed (will retry on first request): {e}")
            self.client = None

    async def cancel(self):
        if self.client:
            try:
                await self.client.interrupt()
            except Exception:
                pass

    async def reset(self):
        await self.close()
        await self._ensure()

    async def close(self):
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass
            self.client = None


class MockAgent(Agent):
    """Deterministic rule-based agent for tests/dev (JARVIS_MOCK_LLM). Exercises the same tool path."""

    async def run(self, text, speak, channel="voice"):
        svc, reg = self.svc, self.svc.registry
        r = router.route(text, svc.settings)
        run_id = svc.tracer.start_run(text, channel)
        svc.tracer.set_route(run_id, r.name, "mock")
        reg.current_run = run_id
        t = text.lower().strip(" .!?")
        try:
            if m := re.match(r"(?:please )?open (.+)", t):
                app = m.group(1)
                await reg.execute("open_application", {"name": app})
                windows = (await reg.execute("list_windows", {})).text
                ok = app.lower() in windows.lower()
                out = f"{app.title()} is open." if ok else f"I tried to open {app}, but I can't see its window."
            elif m := re.match(r"remember (?:that )?(.+)", t):
                res = await reg.execute("remember", {"content": m.group(1), "category": "fact"})
                out = "Noted." if not res.is_error else res.text
            elif t.startswith("what do you know about") or t.startswith("recall"):
                out = (await reg.execute("recall", {"query": t})).text
            elif "time" in t:
                out = (await reg.execute("get_current_datetime", {})).text
            elif m := re.match(r"send (?:an )?email to (\S+) saying (.+)", t):
                d = await reg.execute("draft_email", {"to": m.group(1), "subject": "Quick note", "body": m.group(2)})
                did = re.search(r"Draft (\S+)", d.text).group(1)
                s = await reg.execute("send_draft", {"draft_id": did})
                out = "Sent." if not s.is_error else "I drafted it but didn't send it."
            elif "undo" in t:
                out = await reg.undo_last()
            else:
                out = f"Mock agent heard: {text}"
            speak(out)
            svc.tracer.end_run(run_id, out)
            return out
        finally:
            reg.current_run = None


def make_agent(svc, mock: bool) -> Agent:
    return MockAgent(svc) if mock else ClaudeAgent(svc)
