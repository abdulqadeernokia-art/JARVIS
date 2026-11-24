"""In-process event bus. Components publish events; UI, audit log and others subscribe.

Event names (see ARCHITECTURE.md): agent.started, agent.thinking, agent.text, agent.completed,
agent.failed, tool.started, tool.finished, approval.requested, approval.resolved, voice.state,
voice.transcript, task.created, task.completed, notify, privacy.changed, meeting.segment.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

Handler = Callable[["Event"], None]


@dataclass
class Event:
    type: str
    data: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)


class EventBus:
    def __init__(self):
        self._subs: dict[str, list[Handler]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, event_type: str, handler: Handler) -> None:
        """event_type may be an exact name, a prefix ending in '.*', or '*' for everything."""
        with self._lock:
            self._subs[event_type].append(handler)

    def publish(self, event_type: str, **data: Any) -> Event:
        ev = Event(event_type, data)
        with self._lock:
            handlers = list(self._subs.get(event_type, []))
            handlers += self._subs.get("*", [])
            prefix = event_type.split(".")[0] + ".*"
            handlers += self._subs.get(prefix, [])
        for h in handlers:
            try:
                h(ev)
            except Exception as e:  # a broken subscriber must never break the publisher
                print(f"[events] subscriber error on {event_type}: {e}")
        return ev
