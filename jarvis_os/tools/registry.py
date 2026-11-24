"""Standard tool interface + the single execution path every tool call goes through:

    permission check -> (approval) -> execute with timeout/retry -> audit trace -> undo record -> events
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from ..core.db import Database, dumps, now
from ..core.events import EventBus
from ..core.trace import Tracer
from ..safety.approval import ApprovalBroker
from ..safety.policy import Decision, Risk, decide


@dataclass
class ToolResult:
    text: str
    image_png_b64: str | None = None                     # base64 image (PNG or JPEG, see image_mime)
    image_mime: str = "image/png"
    sources: list[str] = field(default_factory=list)   # provenance, e.g. "gmail:msg/123"
    undo: tuple[str, dict] | None = None                 # (undo_kind, payload) for reversible actions
    is_error: bool = False


Handler = Callable[[dict[str, Any]], Awaitable["ToolResult | str"]]


@dataclass
class Tool:
    name: str
    description: str
    params: dict[str, Any]                     # JSON schema "properties"
    handler: Handler
    risk: Risk = Risk.READ
    required: list[str] | None = None          # default: all params required
    timeout: float = 60.0
    retries: int = 0                           # only applied to READ tools
    summarize: Callable[[dict], str] | None = None   # one-line description for approvals / action log
    category: str = "general"
    risk_fn: Callable[[dict], Risk] | None = None    # context-dependent risk (e.g. typing into a terminal)

    def risk_for(self, args: dict) -> Risk:
        if self.risk_fn:
            try:
                return max(self.risk, self.risk_fn(args))
            except Exception:
                return Risk.DANGEROUS   # can't tell -> be careful
        return self.risk

    def schema(self) -> dict:
        req = list(self.params) if self.required is None else self.required
        return {"type": "object", "properties": self.params, "required": req}


def S(t: str, desc: str, **extra) -> dict:
    """Shorthand for a JSON-schema property."""
    return {"type": t, "description": desc, **extra}


class ToolRegistry:
    def __init__(self, db: Database, bus: EventBus, tracer: Tracer, approvals: ApprovalBroker, settings):
        self.db, self.bus, self.tracer, self.approvals, self.settings = db, bus, tracer, approvals, settings
        self.tools: dict[str, Tool] = {}
        self.undo_handlers: dict[str, Callable[[dict], Awaitable[str]]] = {}
        self.current_run: int | None = None

    def register(self, tool: Tool) -> None:
        if tool.name in self.tools:
            raise ValueError(f"duplicate tool {tool.name}")
        self.tools[tool.name] = tool

    def register_undo(self, kind: str, fn: Callable[[dict], Awaitable[str]]) -> None:
        self.undo_handlers[kind] = fn

    async def execute(self, name: str, args: dict[str, Any]) -> ToolResult:
        run_id = self.current_run
        tool = self.tools.get(name)
        if not tool:
            return ToolResult(f"Unknown tool {name}.", is_error=True)
        summary = tool.summarize(args) if tool.summarize else f"{name} {args}"
        risk = tool.risk_for(args)
        self.bus.publish("tool.started", run_id=run_id, tool=name, summary=summary, risk=risk.name)
        t0 = time.perf_counter()

        decision = decide(risk, self.settings.trust_level, name,
                          self.settings.trusted_tools, self.settings.always_ask_tools)
        if decision == Decision.DENY:
            res = ToolResult(f"Not permitted: trust level {self.settings.trust_level} does not allow "
                             f"{risk.name} actions. Tell the user what you would have done instead.",
                             is_error=True)
            return self._finish(tool, args, res, "denied", t0, run_id)
        if decision == Decision.ASK:
            approved = await self.approvals.request(name, summary, _preview(args), run_id)
            self.tracer.record(run_id, "approval", name, status="approved" if approved else "denied")
            if not approved:
                res = ToolResult("The user did NOT approve this action. It was not performed.", is_error=True)
                return self._finish(tool, args, res, "denied", t0, run_id)

        attempts = 1 + (tool.retries if risk == Risk.READ else 0)
        res = None
        for attempt in range(attempts):
            try:
                out = await asyncio.wait_for(tool.handler(args), timeout=tool.timeout)
                res = out if isinstance(out, ToolResult) else ToolResult(str(out))
                break
            except asyncio.TimeoutError:
                res = ToolResult(f"{name} timed out after {tool.timeout:.0f}s.", is_error=True)
            except Exception as e:
                res = ToolResult(f"{name} failed: {type(e).__name__}: {e}", is_error=True)
            if attempt + 1 < attempts:
                await asyncio.sleep(0.5 * (attempt + 1))

        if res.undo and not res.is_error:
            kind, payload = res.undo
            self.db.execute("INSERT INTO actions(run_id, ts, tool, description, undo_kind, undo_payload) "
                            "VALUES (?,?,?,?,?,?)", (run_id, now(), name, summary, kind, dumps(payload)))
        return self._finish(tool, args, res, "error" if res.is_error else "ok", t0, run_id, risk)

    def _finish(self, tool: Tool, args, res: ToolResult, status: str, t0: float, run_id,
                risk: Risk | None = None) -> ToolResult:
        ms = int((time.perf_counter() - t0) * 1000)
        self.tracer.record(run_id, "tool", tool.name, risk=(risk or tool.risk).name, status=status, latency_ms=ms,
                           detail={"args": _redact(args), "sources": res.sources,
                                   "result": res.text[:300]})
        self.bus.publish("tool.finished", run_id=run_id, tool=tool.name, status=status, ms=ms)
        return res

    async def undo_last(self) -> str:
        import json
        row = self.db.query_one("SELECT * FROM actions WHERE undone=0 AND undo_kind IS NOT NULL "
                                "ORDER BY id DESC LIMIT 1")
        if not row:
            return "There's nothing I can undo."
        fn = self.undo_handlers.get(row["undo_kind"])
        if not fn:
            return f"I can't undo {row['description']}."
        msg = await fn(json.loads(row["undo_payload"]))
        self.db.execute("UPDATE actions SET undone=1 WHERE id=?", (row["id"],))
        self.tracer.record(self.current_run, "undo", row["tool"], status="ok", detail={"action": row["description"]})
        return f"Undone: {row['description']}. {msg}"


def _preview(args: dict) -> str:
    return "\n".join(f"{k}: {v}" for k, v in args.items())


def _redact(args: dict) -> dict:
    out = {}
    for k, v in args.items():
        kl = k.lower()
        if any(s in kl for s in ("password", "secret", "token", "api_key", "apikey", "credential")):
            out[k] = "***"
        elif isinstance(v, str) and len(v) > 200:
            out[k] = v[:200] + "..."
        else:
            out[k] = v
    return out
