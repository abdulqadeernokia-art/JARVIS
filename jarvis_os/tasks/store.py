"""Task engine: tasks, reminders, recurring jobs (briefings, scheduled agent prompts)."""
from __future__ import annotations

import datetime as dt
import json

from ..core.db import Database, dumps, now
from ..core.events import EventBus

KINDS = ("task", "reminder", "briefing", "agent")      # agent = run a prompt through JARVIS at due time
RECURRENCES = ("daily", "weekdays", "weekly", "monthly", "hourly")


def next_occurrence(due: float, recurrence: str) -> float:
    d = dt.datetime.fromtimestamp(due)
    if recurrence == "hourly":
        d += dt.timedelta(hours=1)
    elif recurrence == "daily":
        d += dt.timedelta(days=1)
    elif recurrence == "weekdays":
        d += dt.timedelta(days=1)
        while d.weekday() >= 5:
            d += dt.timedelta(days=1)
    elif recurrence == "weekly":
        d += dt.timedelta(weeks=1)
    elif recurrence == "monthly":
        month = d.month % 12 + 1
        year = d.year + (d.month == 12)
        day = min(d.day, 28)
        d = d.replace(year=year, month=month, day=day)
    else:
        raise ValueError(recurrence)
    return d.timestamp()


def parse_when(value: str | None) -> float | None:
    """Accepts ISO 8601 local time (2026-10-03T15:00) or None."""
    if not value:
        return None
    d = dt.datetime.fromisoformat(value.strip())
    return d.timestamp()


class TaskStore:
    def __init__(self, db: Database, bus: EventBus):
        self.db, self.bus = db, bus

    def create(self, title: str, *, description: str = "", due_at: float | None = None, kind: str = "task",
               recurrence: str | None = None, priority: str = "normal", project: str | None = None,
               source: str = "user", payload: dict | None = None) -> int:
        if kind not in KINDS:
            kind = "task"
        if recurrence and recurrence not in RECURRENCES:
            raise ValueError(f"recurrence must be one of {RECURRENCES}")
        tid = self.db.execute(
            "INSERT INTO tasks(title, description, due_at, kind, recurrence, priority, project, source, payload, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (title, description, due_at, kind, recurrence, priority, project, source, dumps(payload or {}),
             now(), now()))
        self.bus.publish("task.created", id=tid, title=title, due_at=due_at)
        return tid

    def get(self, task_id: int) -> dict | None:
        r = self.db.query_one("SELECT * FROM tasks WHERE id=?", (task_id,))
        return dict(r) if r else None

    def complete(self, task_id: int) -> bool:
        ok = bool(self.db.execute("UPDATE tasks SET status='done', completed_at=?, updated_at=? WHERE id=? "
                                  "AND status='open'", (now(), now(), task_id)))
        if ok:
            self.bus.publish("task.completed", id=task_id)
        return ok

    def cancel(self, task_id: int) -> bool:
        return bool(self.db.execute("UPDATE tasks SET status='cancelled', updated_at=? WHERE id=?", (now(), task_id)))

    def reopen(self, task_id: int) -> None:
        self.db.execute("UPDATE tasks SET status='open', completed_at=NULL, updated_at=? WHERE id=?", (now(), task_id))

    def open_tasks(self, limit: int = 30, kind: str | None = None) -> list[dict]:
        sql = "SELECT * FROM tasks WHERE status='open'"
        params: tuple = ()
        if kind:
            sql += " AND kind=?"
            params = (kind,)
        sql += " ORDER BY due_at IS NULL, due_at, id LIMIT ?"
        return [dict(r) for r in self.db.query(sql, (*params, limit))]

    def due(self, at: float | None = None) -> list[dict]:
        """Open items whose time has come and that haven't fired for this occurrence."""
        at = at or now()
        return [dict(r) for r in self.db.query(
            "SELECT * FROM tasks WHERE status='open' AND due_at IS NOT NULL AND due_at <= ? "
            "AND (fired_at IS NULL OR fired_at < due_at) ORDER BY due_at", (at,))]

    def mark_fired(self, task: dict) -> None:
        """After firing: recurring items move to their next occurrence, reminders close,
        plain tasks stay open (they were only announced as due)."""
        if task["kind"] == "task" and not task["recurrence"]:
            self.db.execute("UPDATE tasks SET fired_at=?, updated_at=? WHERE id=?", (now(), now(), task["id"]))
        elif task["recurrence"]:
            nxt = next_occurrence(task["due_at"], task["recurrence"])
            while nxt <= now():
                nxt = next_occurrence(nxt, task["recurrence"])
            self.db.execute("UPDATE tasks SET due_at=?, fired_at=?, updated_at=? WHERE id=?",
                            (nxt, now(), now(), task["id"]))
        else:
            self.db.execute("UPDATE tasks SET status='done', fired_at=?, completed_at=?, updated_at=? WHERE id=?",
                            (now(), now(), now(), task["id"]))

    @staticmethod
    def fmt(t: dict) -> str:
        due = dt.datetime.fromtimestamp(t["due_at"]).strftime("%a %d %b %H:%M") if t["due_at"] else "no deadline"
        rec = f", repeats {t['recurrence']}" if t["recurrence"] else ""
        proj = f", project {t['project']}" if t["project"] else ""
        return f"[task #{t['id']} | {t['kind']} | {t['priority']} | {due}{rec}{proj}] {t['title']}" + \
            (f" - {t['description']}" if t["description"] else "")

    @staticmethod
    def payload(t: dict) -> dict:
        return json.loads(t["payload"] or "{}")
