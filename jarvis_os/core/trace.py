"""Agent runs, execution trace and provenance ("who told you that?").

Every tool call, model call and approval is written here. We record *actions*, never hidden reasoning.
"""
from __future__ import annotations

import datetime as dt
import json

from .db import Database, dumps, now
from .events import EventBus


class Tracer:
    def __init__(self, db: Database, bus: EventBus):
        self.db, self.bus = db, bus

    def start_run(self, text: str, channel: str = "voice") -> int:
        run_id = self.db.execute("INSERT INTO runs(started_at, input, channel) VALUES (?,?,?)",
                                 (now(), text, channel))
        self.bus.publish("agent.started", run_id=run_id, input=text)
        return run_id

    def set_route(self, run_id: int, route: str, model: str) -> None:
        self.db.execute("UPDATE runs SET route=?, model=? WHERE id=?", (route, model, run_id))
        self.record(run_id, "model", model, detail={"route": route})

    def end_run(self, run_id: int, output: str, status: str = "completed") -> None:
        self.db.execute("UPDATE runs SET ended_at=?, output=?, status=? WHERE id=?",
                        (now(), output, status, run_id))
        self.bus.publish(f"agent.{status}", run_id=run_id, output=output)

    def record(self, run_id: int | None, kind: str, name: str, *, risk: str | None = None,
               status: str | None = None, latency_ms: int | None = None, detail: dict | None = None) -> None:
        self.db.execute(
            "INSERT INTO trace(run_id, ts, kind, name, risk, status, latency_ms, detail) VALUES (?,?,?,?,?,?,?,?)",
            (run_id, now(), kind, name, risk, status, latency_ms, dumps(detail or {})))

    # ---------- reading ----------

    def last_completed_run(self, before: int | None = None) -> int | None:
        sql = "SELECT id FROM runs WHERE status != 'running'"
        params: tuple = ()
        if before:
            sql += " AND id < ?"
            params = (before,)
        row = self.db.query_one(sql + " ORDER BY id DESC LIMIT 1", params)
        return row["id"] if row else None

    def explain(self, run_id: int) -> str:
        """Human-readable trace with sources, for 'how did you get that?' questions."""
        run = self.db.query_one("SELECT * FROM runs WHERE id=?", (run_id,))
        if not run:
            return "No record of that request."
        t0 = run["started_at"]
        lines = [f"Request: {run['input']!r} at {dt.datetime.fromtimestamp(t0):%Y-%m-%d %H:%M}",
                 f"Route: {run['route'] or '?'} -> model {run['model'] or '?'}"]
        for r in self.db.query("SELECT * FROM trace WHERE run_id=? ORDER BY id", (run_id,)):
            d = json.loads(r["detail"])
            rel = f"+{r['ts'] - t0:5.1f}s"
            if r["kind"] == "tool":
                src = f" sources={d['sources']}" if d.get("sources") else ""
                lines.append(f"{rel} tool {r['name']} [{r['risk']}] {r['status']} "
                             f"({r['latency_ms']} ms) args={d.get('args')}{src}")
            elif r["kind"] == "approval":
                lines.append(f"{rel} approval for {r['name']}: {r['status']}")
            elif r["kind"] == "consult":
                lines.append(f"{rel} consulted {r['name']} ({r['latency_ms']} ms)")
            elif r["kind"] != "model":
                lines.append(f"{rel} {r['kind']} {r['name']} {r['status'] or ''}")
        if run["output"]:
            lines.append(f"Final answer: {run['output'][:400]}")
        return "\n".join(lines)

    def recent_activity(self, limit: int = 30) -> list[dict]:
        rows = self.db.query("SELECT t.*, r.input FROM trace t LEFT JOIN runs r ON r.id=t.run_id "
                             "ORDER BY t.id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def metrics(self) -> dict:
        q = self.db.query_one
        runs = q("SELECT COUNT(*) n, SUM(status='completed') ok, SUM(status='failed') failed, "
                 "AVG(ended_at-started_at) avg_s FROM runs")
        tools = q("SELECT COUNT(*) n, SUM(status='error') err, SUM(status='denied') denied, "
                  "AVG(latency_ms) avg_ms FROM trace WHERE kind='tool'")
        appr = q("SELECT COUNT(*) n, SUM(decision='approved') ok FROM approvals")
        return {"runs": runs["n"], "runs_ok": runs["ok"] or 0, "runs_failed": runs["failed"] or 0,
                "avg_run_seconds": round(runs["avg_s"] or 0, 2), "tool_calls": tools["n"],
                "tool_errors": tools["err"] or 0, "tool_denied": tools["denied"] or 0,
                "avg_tool_ms": round(tools["avg_ms"] or 0), "approvals": appr["n"],
                "approved": appr["ok"] or 0}
