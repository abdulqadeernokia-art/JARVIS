"""Gmail + Google Calendar adapters (OAuth desktop flow: credentials.json -> token.json)."""
from __future__ import annotations

import base64
import datetime as dt
import threading
from email.mime.text import MIMEText

from ..config import ROOT
from .base import CalendarAdapter, CalendarEvent, EmailAdapter, EmailMessage, EmailSummary, NotConnected

SCOPES = ["https://www.googleapis.com/auth/gmail.modify", "https://www.googleapis.com/auth/calendar"]
CREDS_FILE = ROOT / "credentials.json"
TOKEN_FILE = ROOT / "token.json"

_lock = threading.Lock()
_creds = None


def _credentials():
    global _creds
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    with _lock:
        if _creds and _creds.valid:
            return _creds
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES) if TOKEN_FILE.exists() else None
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not CREDS_FILE.exists():
                    raise NotConnected("Google isn't connected: credentials.json is missing from the jarvis folder. "
                                       "See README > Connect Google.")
                creds = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), SCOPES).run_local_server(port=0)
            TOKEN_FILE.write_text(creds.to_json())
        _creds = creds
        return creds


def _service(name: str, version: str):
    from googleapiclient.discovery import build
    return build(name, version, credentials=_credentials(), cache_discovery=False)


def _headers(msg) -> dict:
    return {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}


def _body(payload) -> str:
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", "ignore")
    for part in payload.get("parts", []) or []:
        text = _body(part)
        if text:
            return text
    return ""


class GmailAdapter(EmailAdapter):
    name = "gmail"

    def search(self, query, max_results=10):
        svc = _service("gmail", "v1")
        res = svc.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
        out = []
        for m in res.get("messages", []):
            full = svc.users().messages().get(userId="me", id=m["id"], format="metadata",
                                              metadataHeaders=["From", "Subject", "Date"]).execute()
            h = _headers(full)
            out.append(EmailSummary(m["id"], h.get("From", "?"), h.get("Subject", "(no subject)"),
                                    h.get("Date", "?"), full.get("snippet", ""), full.get("labelIds", [])))
        return out

    def read(self, message_id):
        msg = _service("gmail", "v1").users().messages().get(userId="me", id=message_id, format="full").execute()
        h = _headers(msg)
        return EmailMessage(message_id, h.get("From", "?"), h.get("Subject", ""), h.get("Date", ""),
                            msg.get("snippet", ""), msg.get("labelIds", []),
                            body=(_body(msg["payload"]) or msg.get("snippet", ""))[:12000],
                            thread_id=msg.get("threadId", ""), to=h.get("To", ""))

    def create_draft(self, to, subject, body, reply_to_id=None):
        mime = MIMEText(body)
        mime["to"], mime["subject"] = to, subject
        message: dict = {}
        if reply_to_id:
            orig = _service("gmail", "v1").users().messages().get(
                userId="me", id=reply_to_id, format="metadata", metadataHeaders=["Message-ID"]).execute()
            mid = _headers(orig).get("Message-ID")
            if mid:
                mime["In-Reply-To"] = mime["References"] = mid
            message["threadId"] = orig.get("threadId")
        message["raw"] = base64.urlsafe_b64encode(mime.as_bytes()).decode()
        d = _service("gmail", "v1").users().drafts().create(userId="me", body={"message": message}).execute()
        return d["id"]

    def draft_preview(self, draft_id):
        d = _service("gmail", "v1").users().drafts().get(userId="me", id=draft_id, format="full").execute()
        h = _headers(d["message"])
        return {"to": h.get("To", ""), "subject": h.get("Subject", ""), "body": _body(d["message"]["payload"])}

    def send_draft(self, draft_id):
        r = _service("gmail", "v1").users().drafts().send(userId="me", body={"id": draft_id}).execute()
        return r.get("id", "")

    def delete_draft(self, draft_id):
        _service("gmail", "v1").users().drafts().delete(userId="me", id=draft_id).execute()

    def modify(self, message_id, add=None, remove=None):
        _service("gmail", "v1").users().messages().modify(
            userId="me", id=message_id, body={"addLabelIds": add or [], "removeLabelIds": remove or []}).execute()


class GoogleCalendarAdapter(CalendarAdapter):
    name = "google-calendar"

    def list_events(self, start_iso, end_iso):
        res = _service("calendar", "v3").events().list(
            calendarId="primary", timeMin=_aware(start_iso), timeMax=_aware(end_iso),
            singleEvents=True, orderBy="startTime", maxResults=50).execute()
        return [CalendarEvent(e["id"], e.get("summary", "(no title)"),
                              e["start"].get("dateTime", e["start"].get("date")),
                              e["end"].get("dateTime", e["end"].get("date")), e.get("location", ""),
                              [a.get("email", "") for a in e.get("attendees", [])], e.get("description", ""))
                for e in res.get("items", [])]

    def create_event(self, title, start_iso, end_iso, description="", location="", attendees=None):
        body = {"summary": title, "description": description, "location": location,
                "start": {"dateTime": _aware(start_iso)}, "end": {"dateTime": _aware(end_iso)}}
        if attendees:
            body["attendees"] = [{"email": a} for a in attendees]
        e = _service("calendar", "v3").events().insert(calendarId="primary", body=body).execute()
        return CalendarEvent(e["id"], title, body["start"]["dateTime"], body["end"]["dateTime"], location,
                             attendees or [], description)

    def delete_event(self, event_id):
        _service("calendar", "v3").events().delete(calendarId="primary", eventId=event_id).execute()


def _aware(iso: str) -> str:
    d = dt.datetime.fromisoformat(iso)
    if not d.tzinfo:
        d = d.replace(tzinfo=dt.datetime.now().astimezone().tzinfo)
    return d.isoformat()
