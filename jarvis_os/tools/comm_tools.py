"""Email and calendar tools. External content is wrapped as untrusted data.

Email flow: draft_email (PREPARE) -> preview -> send_draft (EXTERNAL, approval by default).
"""
from __future__ import annotations

import datetime as dt

from ..connectors.base import NotConnected
from ..safety.policy import Risk, wrap_untrusted
from .registry import S, Tool, ToolResult


def register(svc) -> None:
    reg, mail, cal = svc.registry, svc.email, svc.calendar

    def guarded(fn):
        async def run(a):
            import asyncio
            try:
                return await asyncio.to_thread(fn, a)
            except NotConnected as e:
                return ToolResult(str(e), is_error=True)
        return run

    # ---------------- email ----------------
    def search(a):
        rows = mail.search(a.get("query") or "in:inbox is:unread", max(1, min(int(a.get("max_results") or 10), 30)))
        if not rows:
            return "No emails match."
        text = "\n".join(f"id={m.id} | from: {m.sender} | subject: {m.subject} | date: {m.date} | "
                         f"labels: {','.join(m.labels)} | snippet: {m.snippet}" for m in rows)
        return ToolResult(wrap_untrusted(text, f"{mail.name} search"), sources=[f"{mail.name}:{m.id}" for m in rows])
    reg.register(Tool("search_email",
                      "Search email. Gmail query syntax, e.g. 'is:unread in:inbox', 'from:john newer_than:7d', "
                      "'subject:contract'. Labels show IMPORTANT / CATEGORY_PROMOTIONS etc. for triage.",
                      {"query": S("string", "Search query."), "max_results": S("integer", "1-30")},
                      guarded(search), required=[], retries=1, timeout=45, category="email"))

    def read(a):
        m = mail.read(a["message_id"])
        text = f"From: {m.sender}\nTo: {m.to}\nSubject: {m.subject}\nDate: {m.date}\n\n{m.body}"
        return ToolResult(wrap_untrusted(text, f"email from {m.sender}"), sources=[f"{mail.name}:{m.id}"])
    reg.register(Tool("read_email", "Read one email in full.", {"message_id": S("string", "Id from search_email.")},
                      guarded(read), retries=1, timeout=45, category="email"))

    def draft(a):
        did = mail.create_draft(a["to"], a["subject"], a["body"], a.get("reply_to_message_id") or None)
        return ToolResult(f"Draft {did} created (NOT sent). Read it back or summarise it for the user, then "
                          f"call send_draft only if they want it sent.", undo=("draft_create", {"id": did}))
    reg.register(Tool("draft_email", "Create an email draft (does not send). For replies pass reply_to_message_id "
                      "so it threads correctly. To revise, create a new draft and delete the old one.",
                      {"to": S("string", "Recipient email address(es)."), "subject": S("string", ""),
                       "body": S("string", "Plain-text body, in the user's style."),
                       "reply_to_message_id": S("string", "Optional message id being replied to.")},
                      guarded(draft), Risk.PREPARE, required=["to", "subject", "body"],
                      summarize=lambda a: f"draft email to {a['to']}: {a['subject']}", category="email"))
    reg.register_undo("draft_create", lambda p: _thread(mail.delete_draft, p["id"], "Draft deleted."))

    def delete_draft(a):
        mail.delete_draft(a["draft_id"])
        return "Draft deleted."
    reg.register(Tool("delete_draft", "Delete an unsent draft.", {"draft_id": S("string", "")},
                      guarded(delete_draft), Risk.PREPARE, category="email"))

    def send(a):
        mail.send_draft(a["draft_id"])
        return ToolResult("Sent.", sources=[f"{mail.name}:draft:{a['draft_id']}"])

    def send_summary(a):
        try:
            p = mail.draft_preview(a["draft_id"])
            return f"send email to {p['to']}, subject '{p['subject']}'"
        except Exception:
            return f"send draft {a['draft_id']}"
    reg.register(Tool("send_draft", "Send a previously created draft. External action: the user is asked to "
                      "approve unless they've trusted this tool.", {"draft_id": S("string", "")},
                      guarded(send), Risk.EXTERNAL, summarize=send_summary, category="email"))

    def archive(a):
        mail.modify(a["message_id"], remove=["INBOX"])
        return ToolResult("Archived.", undo=("email_unarchive", {"id": a["message_id"]}))
    reg.register(Tool("archive_email", "Archive an email (remove from inbox; reversible).",
                      {"message_id": S("string", "")}, guarded(archive), Risk.LOCAL,
                      summarize=lambda a: f"archive email {a['message_id']}", category="email"))
    reg.register_undo("email_unarchive", lambda p: _thread(lambda i: mail.modify(i, add=["INBOX"]), p["id"],
                                                           "Back in the inbox."))

    def mark(a):
        read_flag = str(a.get("read", True)).lower() in ("true", "1", "yes")
        mail.modify(a["message_id"], remove=["UNREAD"]) if read_flag else mail.modify(a["message_id"], add=["UNREAD"])
        return "Marked as read." if read_flag else "Marked as unread."
    reg.register(Tool("mark_email", "Mark an email read or unread.",
                      {"message_id": S("string", ""), "read": S("boolean", "true = read, false = unread")},
                      guarded(mark), Risk.LOCAL, required=["message_id"], category="email"))

    def label(a):
        mail.modify(a["message_id"], add=[a["label_id"]])
        return "Labelled."
    reg.register(Tool("label_email", "Add a label id (e.g. STARRED, IMPORTANT) to an email.",
                      {"message_id": S("string", ""), "label_id": S("string", "")},
                      guarded(label), Risk.LOCAL, category="email"))

    # ---------------- calendar ----------------
    def events(a):
        start = a.get("start") or dt.datetime.now().isoformat(timespec="seconds")
        end = a.get("end") or (dt.datetime.fromisoformat(start[:19]) + dt.timedelta(days=1)).isoformat()
        rows = cal.list_events(start, end)
        if not rows:
            return "No events in that window."
        text = "\n".join(f"id={e.id} | {e.start} -> {e.end} | {e.title}"
                         f"{' @ ' + e.location if e.location else ''}"
                         f"{' | attendees: ' + ', '.join(e.attendees) if e.attendees else ''}" for e in rows)
        return ToolResult(wrap_untrusted(text, "calendar"), sources=[f"{cal.name}:{e.id}" for e in rows])
    reg.register(Tool("list_calendar_events", "List calendar events between two ISO local datetimes "
                      "(defaults: now to 24h later).",
                      {"start": S("string", "ISO start"), "end": S("string", "ISO end")},
                      guarded(events), required=[], retries=1, timeout=45, category="calendar"))

    def create(a):
        attendees = [x.strip() for x in (a.get("attendees") or "").split(",") if x.strip()]
        e = cal.create_event(a["title"], a["start"], a["end"], a.get("description") or "",
                             a.get("location") or "", attendees)
        return ToolResult(f"Event created: {e.title} {e.start} -> {e.end}", undo=("calendar_create", {"id": e.id}),
                          sources=[f"{cal.name}:{e.id}"])
    risk_note = "Inviting attendees sends them email, so it needs approval."
    reg.register(Tool("create_calendar_event", f"Create a calendar event. {risk_note}",
                      {"title": S("string", ""), "start": S("string", "ISO local start"),
                       "end": S("string", "ISO local end"), "description": S("string", ""),
                       "location": S("string", ""), "attendees": S("string", "Comma-separated emails (optional).")},
                      guarded(create), Risk.EXTERNAL, required=["title", "start", "end"],
                      summarize=lambda a: f"add '{a['title']}' at {a['start']} to your calendar"
                      + (f" and invite {a['attendees']}" if a.get("attendees") else ""), category="calendar"))
    reg.register_undo("calendar_create", lambda p: _thread(cal.delete_event, p["id"], "Event removed."))


async def _thread(fn, arg, msg):
    import asyncio
    await asyncio.to_thread(fn, arg)
    return msg
