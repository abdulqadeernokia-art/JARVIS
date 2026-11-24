"""Dictation ("write while I speak") and meeting mode."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import re
import threading

from ..core.db import dumps, now
from ..safety.policy import Risk
from .registry import S, Tool, ToolResult

END_PHRASES = re.compile(r"\b(end|stop|finish) (the )?dictation\b|\bthat'?s (it|all)\b", re.I)


class MeetingSession:
    def __init__(self, svc, title: str):
        self.svc, self.title = svc, title
        self.id = svc.db.execute("INSERT INTO meetings(title, started_at) VALUES (?,?)", (title, now()))
        self.started = now()
        self.segments: list[dict] = []
        self.lock = threading.Lock()

    def on_segment(self, text: str, t: float) -> None:
        seg = {"t": round(t - self.started, 1), "clock": dt.datetime.fromtimestamp(t).strftime("%H:%M:%S"),
               "text": text}
        with self.lock:
            self.segments.append(seg)
            self.svc.db.execute("UPDATE meetings SET segments=? WHERE id=?", (dumps(self.segments), self.id))
        self.svc.bus.publish("meeting.segment", meeting_id=self.id, **seg)

    def transcript(self) -> str:
        with self.lock:
            return "\n".join(f"[{s['clock']}] {s['text']}" for s in self.segments)


def register(svc) -> None:
    reg = svc.registry
    state: dict = {"meeting": None}

    async def dictate(a):
        if not svc.voice:
            return ToolResult("No microphone/voice layer available.", is_error=True)
        verbatim = (a.get("mode") or "clean") == "verbatim"
        svc.voice.say("Go ahead. Say 'end dictation' when you're finished.")
        await asyncio.to_thread(svc.voice.wait_spoken)
        svc.bus.publish("voice.state", state="dictating")
        parts: list[str] = []
        silent_rounds = 0
        while True:
            text = await asyncio.to_thread(svc.voice.listen, 8, 2.0, 60)
            if not text:
                silent_rounds += 1
                if parts and silent_rounds >= 1 or silent_rounds >= 2:
                    break
                continue
            silent_rounds = 0
            m = END_PHRASES.search(text)
            if m:
                parts.append(text[:m.start()].strip())
                break
            parts.append(text.strip())
            svc.bus.publish("voice.transcript", text=" ".join(parts), partial=True)
        transcript = " ".join(p for p in parts if p)
        if not transcript:
            return "I didn't hear any dictation."
        instruction = ("Use this text EXACTLY as spoken; do not rewrite it (only add basic punctuation)."
                       if verbatim else
                       "Clean it up: fix grammar and filler words, infer paragraphs/formatting, keep the meaning "
                       "and the user's voice. Then continue with the purpose (draft email/note) and read back or "
                       "summarise before sending anything.")
        return ToolResult(f"Dictated text ({'verbatim' if verbatim else 'to clean'}):\n\"\"\"{transcript}\"\"\"\n"
                          f"{instruction}\nPurpose: {a.get('purpose') or 'unspecified'}", sources=["dictation"])
    reg.register(Tool("dictate", "Listen to the user dictating long-form text (an email, note, document) until they "
                      "say 'end dictation' or pause. mode 'verbatim' keeps their exact words; 'clean' lets you "
                      "polish it.",
                      {"mode": S("string", "", enum=["clean", "verbatim"]),
                       "purpose": S("string", "What the text is for, e.g. 'email to Sarah'.")},
                      dictate, required=[], timeout=600, category="voice"))

    async def start_meeting(a):
        if not svc.voice:
            return ToolResult("No microphone available.", is_error=True)
        if state["meeting"]:
            return "Meeting mode is already on."
        m = MeetingSession(svc, a.get("title") or f"Meeting {dt.datetime.now():%d %b %H:%M}")
        state["meeting"] = m
        svc.voice.start_meeting(m.on_segment)
        svc.bus.publish("meeting.started", meeting_id=m.id, title=m.title)
        return (f"Meeting mode on (meeting #{m.id}). I'm transcribing continuously with timestamps. "
                "Speaker identification isn't available with the current speech engine.")
    reg.register(Tool("start_meeting_mode", "Start continuously transcribing a meeting.",
                      {"title": S("string", "Optional meeting title.")}, start_meeting, Risk.PREPARE,
                      required=[], category="meeting"))

    async def stop_meeting(a):
        m = state["meeting"]
        if not m:
            return "Meeting mode isn't on."
        svc.voice.stop_meeting()
        state["meeting"] = None
        svc.db.execute("UPDATE meetings SET ended_at=? WHERE id=?", (now(), m.id))
        svc.bus.publish("meeting.stopped", meeting_id=m.id)
        tr = m.transcript() or "(nothing was transcribed)"
        return ToolResult(
            f"Meeting #{m.id} '{m.title}' ended after {(now() - m.started) / 60:.0f} min.\nTRANSCRIPT:\n{tr}\n\n"
            "Now: write a summary note (create_note kind=meeting) with sections Summary, Decisions, Action Items "
            "(owner -> task, deadline), Open Questions, Important Moments (with timestamps). Create tasks for the "
            "user's own action items. Offer to draft follow-up emails. Tell the user briefly what you saved.",
            sources=[f"meeting:{m.id}"])
    reg.register(Tool("stop_meeting_mode", "Stop meeting transcription and get the transcript to summarise.", {},
                      stop_meeting, Risk.PREPARE, timeout=30, category="meeting"))

    async def meeting_status(a):
        m = state["meeting"]
        if not m:
            return "Meeting mode is off."
        return f"Meeting '{m.title}' running {(now() - m.started) / 60:.0f} min. Transcript so far:\n{m.transcript()}"
    reg.register(Tool("meeting_transcript_so_far", "Read the live meeting transcript so far.", {}, meeting_status,
                      category="meeting"))

    async def past_meeting(a):
        row = svc.db.query_one("SELECT * FROM meetings WHERE id=?", (int(a["meeting_id"]),)) if a.get("meeting_id") \
            else svc.db.query_one("SELECT * FROM meetings ORDER BY id DESC LIMIT 1")
        if not row:
            return "No recorded meetings."
        segs = json.loads(row["segments"])
        return ToolResult(f"Meeting #{row['id']} {row['title']}:\n" +
                          "\n".join(f"[{s['clock']}] {s['text']}" for s in segs), sources=[f"meeting:{row['id']}"])
    reg.register(Tool("get_meeting_transcript", "Transcript of a past meeting (latest by default).",
                      {"meeting_id": S("integer", "")}, past_meeting, required=[], category="meeting"))
