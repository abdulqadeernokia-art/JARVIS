"""Multi-model consultation with honest attribution."""
from __future__ import annotations

import asyncio
import time

from .registry import S, Tool, ToolResult


def register(svc) -> None:
    from ..agent.providers import default_providers
    reg = svc.registry
    providers = getattr(svc, "providers", None) or default_providers(svc.settings)
    svc.providers = providers

    async def consult(a):
        names = [n.strip().lower() for n in (a.get("providers") or "claude").split(",") if n.strip()]
        prompt = a["question"] + (f"\n\nMaterial:\n{a['material']}" if a.get("material") else "")
        system = ("Give an independent, well-reasoned analysis. Separate facts from interpretation, flag "
                  "uncertainty, be concise.")

        async def one(name):
            p = providers.get(name)
            if not p:
                return name, None, f"Unknown provider '{name}'. Known: {list(providers)}"
            if not p.available():
                return name, None, f"{name} is not configured (no API key), so it was NOT consulted."
            t0 = time.perf_counter()
            try:
                text, label = await p.complete(prompt, system)
            except Exception as e:
                return name, None, f"{name} failed: {e}"
            svc.tracer.record(reg.current_run, "consult", label, status="ok",
                              latency_ms=int((time.perf_counter() - t0) * 1000),
                              detail={"question": a["question"][:200]})
            return name, label, text

        results = await asyncio.gather(*(one(n) for n in names))
        out, sources = [], []
        for name, label, text in results:
            if label:
                out.append(f"=== Independent opinion from {label} ===\n{text}")
                sources.append(f"model:{label}")
            else:
                out.append(f"=== {name}: not available === {text}")
        out.append("When you report this, attribute each point to the model that actually produced it, compare "
                   "agreements/differences, and never claim a model was consulted if it was not.")
        return ToolResult("\n\n".join(out), sources=sources)

    available = [n for n, p in providers.items() if p.available()]
    reg.register(Tool("consult_model",
                      "Ask other AI models for an independent opinion or cross-check (contracts, decisions, "
                      f"analysis). Available now: {', '.join(available)}. Comma-separate to ask several.",
                      {"question": S("string", "The question, self-contained."),
                       "material": S("string", "Relevant text to analyse."),
                       "providers": S("string", "e.g. 'claude' or 'claude,openai'")},
                      consult, required=["question"], timeout=300, category="ai"))
