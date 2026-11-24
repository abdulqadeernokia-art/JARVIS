"""Scheduler + proactive monitor. Fires reminders, scheduled agent jobs, the daily briefing, and
calendar heads-ups. Produces Notifications; the app decides how to deliver them (voice, UI)."""
from __future__ import annotations

import asyncio
import datetime as dt
from dataclasses import dataclass

from ..connectors.base import NotConnected
from .store import TaskStore

BRIEFING_PROMPT = ("Give me my daily briefing: today's calendar, emails that need my attention (not newsletters), "
                   "tasks and follow-ups due, and anything I should prepare for. Keep the spoken version under a "
                   "minute and save the full version as a note (kind briefing).")


@dataclass
class Notification:
    text: str                      # spoken / shown
    agent_prompt: str | None = None  # if set, run this through the agent (scheduled job / briefing)
    follow_up: bool = False        # keep listening afterwards (e.g. "want a briefing?")
    source: str = ""


class Scheduler:
    def __init__(self, svc, deliver, interval: float = 20.0):
        self.svc, self.deliver, self.interval = svc, deliver, interval
        self._announced_events: set[str] = set()
        self._last_calendar_check = 0.0
        self._calendar_warned = False

    def ensure_briefing(self) -> None:
        bt = self.svc.settings.briefing_time
        existing = self.svc.tasks.open_tasks(kind="briefing")
        if not bt:
            for t in existing:
                self.svc.tasks.cancel(t["id"])
            return
        if existing:
            return
        h, m = (int(x) for x in bt.split(":"))
        due = dt.datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)
        if due <= dt.datetime.now():
            due += dt.timedelta(days=1)
        self.svc.tasks.create("Daily briefing", kind="briefing", due_at=due.timestamp(), recurrence="daily",
                              source="system", payload={"prompt": BRIEFING_PROMPT})

    async def run(self, stop: asyncio.Event) -> None:
        self.ensure_briefing()
        while not stop.is_set():
            try:
                await self.tick()
            except Exception as e:
                print(f"[scheduler] {e}")
            try:
                await asyncio.wait_for(stop.wait(), self.interval)
            except asyncio.TimeoutError:
                pass

    async def tick(self, now: float | None = None) -> list[Notification]:
        now = now or dt.datetime.now().timestamp()
        out: list[Notification] = []
        for t in self.svc.tasks.due(now):
            late = now - t["due_at"] > 6 * 3600     # missed while JARVIS was off: mention, don't run old jobs
            if t["kind"] == "reminder":
                out.append(Notification(f"Reminder, {self.svc.settings.user_name}: {t['title']}.", source=f"task:{t['id']}"))
            elif t["kind"] in ("agent", "briefing") and not late:
                prompt = TaskStore.payload(t).get("prompt") or t["title"]
                out.append(Notification("", agent_prompt=prompt, source=f"task:{t['id']}"))
            elif t["kind"] == "task":
                out.append(Notification(f"Heads up: {t['title']} is due now.", source=f"task:{t['id']}"))
            self.svc.tasks.mark_fired(t)
        if self.svc.settings.proactive and not self.svc.privacy and now - self._last_calendar_check > 300:
            self._last_calendar_check = now
            out += await self._calendar_headsup(now)
        for n in out:
            self.svc.bus.publish("notify", text=n.text or n.agent_prompt, source=n.source)
            await self.deliver(n)
        return out

    async def _calendar_headsup(self, now: float) -> list[Notification]:
        start = dt.datetime.fromtimestamp(now)
        try:
            events = await asyncio.to_thread(self.svc.calendar.list_events, start.isoformat(timespec="seconds"),
                                             (start + dt.timedelta(minutes=20)).isoformat(timespec="seconds"))
        except NotConnected:
            if not self._calendar_warned:
                print("[scheduler] calendar not connected; proactive calendar checks paused")
                self._calendar_warned = True
            return []
        out = []
        for e in events:
            if e.id in self._announced_events or "T" not in e.start:
                continue
            self._announced_events.add(e.id)
            mins = max(1, round((dt.datetime.fromisoformat(e.start[:19]) - start).total_seconds() / 60))
            out.append(Notification(f"You have {e.title} in {mins} minutes. Would you like a quick briefing?",
                                    follow_up=True, source=f"calendar:{e.id}"))
        return out
