"""Approval broker: one pending request at a time, resolvable by voice or by the UI (first answer wins)."""
from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from typing import Callable

from ..core.db import Database, now
from ..core.events import EventBus


@dataclass
class ApprovalRequest:
    id: int
    tool: str
    summary: str          # one line, spoken
    preview: str          # full detail, shown in the UI
    decision: str | None = None
    decided_by: str | None = None
    _done: threading.Event = field(default_factory=threading.Event)

    def resolve(self, decision: str, by: str) -> bool:
        if self._done.is_set():
            return False
        self.decision, self.decided_by = decision, by
        self._done.set()
        return True


# A voice asker speaks the question and returns "approved" / "denied" / None (no clear answer).
VoiceAsker = Callable[[ApprovalRequest], str | None]


class ApprovalBroker:
    def __init__(self, db: Database, bus: EventBus, timeout: float = 45.0):
        self.db, self.bus, self.timeout = db, bus, timeout
        self.voice_asker: VoiceAsker | None = None
        self.auto_decision: str | None = None   # tests / headless: "approved" or "denied"
        self.pending: ApprovalRequest | None = None

    async def request(self, tool: str, summary: str, preview: str, run_id: int | None = None) -> bool:
        rid = self.db.execute("INSERT INTO approvals(run_id, ts, tool, summary) VALUES (?,?,?,?)",
                              (run_id, now(), tool, summary))
        req = ApprovalRequest(rid, tool, summary, preview)
        self.pending = req
        self.bus.publish("approval.requested", id=rid, tool=tool, summary=summary, preview=preview)

        if self.auto_decision:
            req.resolve(self.auto_decision, "policy")
        elif self.voice_asker:
            def ask_voice():
                answer = self.voice_asker(req)
                if answer:
                    req.resolve(answer, "voice")
            threading.Thread(target=ask_voice, daemon=True).start()

        ok = await asyncio.to_thread(req._done.wait, self.timeout)
        if not ok:
            req.resolve("denied", "timeout")
        self.pending = None
        self.db.execute("UPDATE approvals SET decision=?, decided_by=?, decided_at=? WHERE id=?",
                        (req.decision, req.decided_by, now(), rid))
        self.bus.publish("approval.resolved", id=rid, tool=tool, decision=req.decision, by=req.decided_by)
        return req.decision == "approved"

    def resolve_pending(self, decision: str, by: str = "ui") -> bool:
        req = self.pending
        return bool(req and req.resolve(decision, by))
