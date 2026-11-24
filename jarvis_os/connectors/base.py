"""Provider-neutral connector interfaces. New services (Outlook, Slack, VoIP...) implement these."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class NotConnected(Exception):
    """The service isn't set up yet (e.g. missing OAuth credentials)."""


@dataclass
class EmailSummary:
    id: str
    sender: str
    subject: str
    date: str
    snippet: str
    labels: list[str] = field(default_factory=list)


@dataclass
class EmailMessage(EmailSummary):
    body: str = ""
    thread_id: str = ""
    to: str = ""


class EmailAdapter(ABC):
    name = "email"

    @abstractmethod
    def search(self, query: str, max_results: int = 10) -> list[EmailSummary]: ...
    @abstractmethod
    def read(self, message_id: str) -> EmailMessage: ...
    @abstractmethod
    def create_draft(self, to: str, subject: str, body: str, reply_to_id: str | None = None) -> str: ...
    @abstractmethod
    def send_draft(self, draft_id: str) -> str: ...
    @abstractmethod
    def delete_draft(self, draft_id: str) -> None: ...
    @abstractmethod
    def modify(self, message_id: str, add: list[str] | None = None, remove: list[str] | None = None) -> None: ...
    @abstractmethod
    def draft_preview(self, draft_id: str) -> dict: ...


@dataclass
class CalendarEvent:
    id: str
    title: str
    start: str
    end: str
    location: str = ""
    attendees: list[str] = field(default_factory=list)
    description: str = ""


class CalendarAdapter(ABC):
    name = "calendar"

    @abstractmethod
    def list_events(self, start_iso: str, end_iso: str) -> list[CalendarEvent]: ...
    @abstractmethod
    def create_event(self, title: str, start_iso: str, end_iso: str, description: str = "",
                     location: str = "", attendees: list[str] | None = None) -> CalendarEvent: ...
    @abstractmethod
    def delete_event(self, event_id: str) -> None: ...


class CallAdapter(ABC):
    """Telephony/VoIP abstraction. No provider is wired in yet (see ARCHITECTURE.md, phase 9+)."""
    name = "calls"

    @abstractmethod
    def place_call(self, number: str) -> str: ...
