"""Dependency container: builds every component once and hands them to tools/agent/UI."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from . import config
from .computer.controller import ComputerController, MockController
from .connectors.base import CalendarAdapter, EmailAdapter
from .core.db import Database
from .core.events import EventBus
from .core.trace import Tracer
from .memory.store import ContactStore, MemoryStore, NoteStore
from .safety.approval import ApprovalBroker
from .tasks.store import TaskStore
from .tools.registry import ToolRegistry


class VoiceIO(Protocol):
    """What tools need from the voice layer (dictation, meetings, spoken confirmations)."""
    def say(self, text: str) -> None: ...
    def wait_spoken(self) -> None: ...
    def listen(self, start_timeout: float = 6, silence: float = 1.3, max_seconds: float = 30) -> str: ...
    def start_meeting(self, on_segment) -> None: ...
    def stop_meeting(self) -> None: ...


@dataclass
class Services:
    settings: config.Settings
    bus: EventBus
    db: Database
    tracer: Tracer
    approvals: ApprovalBroker
    registry: ToolRegistry
    memory: MemoryStore
    notes: NoteStore
    contacts: ContactStore
    tasks: TaskStore
    email: EmailAdapter
    calendar: CalendarAdapter
    computer: ComputerController
    voice: VoiceIO | None = None
    privacy: bool = False


def build_services(settings: config.Settings | None = None, db_path: str | Path | None = None, *,
                   mock_email: bool | None = None, mock_calendar: bool | None = None,
                   mock_computer: bool | None = None) -> Services:
    settings = settings or config.Settings.load()
    bus = EventBus()
    db = Database(db_path or config.DATA_DIR / "jarvis.db")
    tracer = Tracer(db, bus)
    approvals = ApprovalBroker(db, bus, settings.approval_timeout)
    registry = ToolRegistry(db, bus, tracer, approvals, settings)

    use_mock = lambda flag, default: default if flag is None else flag  # noqa: E731
    if use_mock(mock_email, config.MOCK_EMAIL):
        from .connectors.mock import MockEmailAdapter
        email: EmailAdapter = MockEmailAdapter()
    else:
        from .connectors.google import GmailAdapter
        email = GmailAdapter()
    if use_mock(mock_calendar, config.MOCK_CALENDAR):
        from .connectors.mock import MockCalendarAdapter
        calendar: CalendarAdapter = MockCalendarAdapter()
    else:
        from .connectors.google import GoogleCalendarAdapter
        calendar = GoogleCalendarAdapter()
    if use_mock(mock_computer, config.MOCK_COMPUTER):
        computer: ComputerController = MockController()
    else:
        from .computer.controller import WindowsController
        computer = WindowsController()

    svc = Services(settings, bus, db, tracer, approvals, registry, MemoryStore(db), NoteStore(db),
                   ContactStore(db), TaskStore(db, bus), email, calendar, computer)
    from .tools import load_all
    load_all(svc)
    return svc
