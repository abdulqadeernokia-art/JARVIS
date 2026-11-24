"""Memory, notes, tasks, contacts, provenance, undo and settings tools."""
from __future__ import annotations

import datetime as dt

from ..memory.store import CATEGORIES
from ..safety.policy import TRUST_NAMES, Risk
from ..tasks.store import RECURRENCES, TaskStore, parse_when
from .registry import S, Tool, ToolResult


def register(svc) -> None:
    reg, mem, notes, tasks, contacts = svc.registry, svc.memory, svc.notes, svc.tasks, svc.contacts

    # ---------------- time ----------------
    async def now(a):
        return dt.datetime.now().astimezone().strftime("%A %d %B %Y, %H:%M:%S (%Z, UTC%z)")
    reg.register(Tool("get_current_datetime", "Current local date, time and timezone.", {}, now))

    # ---------------- memory ----------------
    async def remember(a):
        mid, msg = mem.add(a["content"], a["category"], a.get("source") or "user said",
                           float(a.get("importance", 0.5)))
        return ToolResult(f"{msg} (memory #{mid})" if mid else msg, undo=("memory_add", {"id": mid}) if mid else None)
    reg.register(Tool(
        "remember", "Store a long-term memory about the user or their world. Only store things worth keeping: "
        "identity, preferences, people, projects, decisions, persistent facts, habits. Write it as a standalone fact.",
        {"content": S("string", "The fact, written so it makes sense on its own later."),
         "category": S("string", "Category.", enum=list(CATEGORIES)),
         "importance": S("number", "0..1, how important (default 0.5)."),
         "source": S("string", "Where it came from, e.g. 'user said', 'email from Sarah 29 Sep'.")},
        remember, Risk.PREPARE, required=["content", "category"], summarize=lambda a: f"remember: {a['content']}",
        category="memory"))
    reg.register_undo("memory_add", lambda p: _async(mem.forget(p["id"]) and "Memory removed."))

    async def recall(a):
        rows = mem.search(a["query"], int(a.get("limit") or 8), a.get("category"))
        if not rows:
            return "No stored memories match. Do not guess; say you don't have it stored."
        return ToolResult("\n".join(mem.fmt(r) for r in rows), sources=[f"memory:{r['id']}" for r in rows])
    reg.register(Tool("recall", "Search long-term memory (what the user told you before, people, decisions).",
                      {"query": S("string", "What to look for."),
                       "category": S("string", "Optional category filter.", enum=list(CATEGORIES)),
                       "limit": S("integer", "Max results.")}, recall, required=["query"], category="memory"))

    async def forget(a):
        ok = mem.forget(int(a["memory_id"]))
        return ToolResult("Forgotten." if ok else "No such memory.", undo=("memory_restore", {"id": int(a["memory_id"])}))
    reg.register(Tool("forget_memory", "Delete a stored memory by id (when it is wrong or the user asks).",
                      {"memory_id": S("integer", "Memory id from recall.")}, forget, Risk.PREPARE,
                      summarize=lambda a: f"forget memory #{a['memory_id']}", category="memory"))
    reg.register_undo("memory_restore", lambda p: _async(mem.restore(p["id"]) or "Memory restored."))

    async def update_mem(a):
        return "Updated." if mem.update(int(a["memory_id"]), a["content"]) else "No such memory."
    reg.register(Tool("update_memory", "Correct or refresh an existing memory.",
                      {"memory_id": S("integer", "Memory id."), "content": S("string", "New content.")},
                      update_mem, Risk.PREPARE, category="memory"))

    # ---------------- notes ----------------
    async def note_create(a):
        nid = notes.create(a["title"], a["body"], a.get("kind") or "quick", a.get("tags") or "",
                           a.get("source") or "user")
        return ToolResult(f"Note #{nid} saved.", undo=("note_create", {"id": nid}))
    reg.register(Tool("create_note", "Save a note (quick note, meeting notes, project note, dictation).",
                      {"title": S("string", "Short title."), "body": S("string", "Note text."),
                       "kind": S("string", "quick | meeting | project | voice | briefing"),
                       "tags": S("string", "Comma-separated tags."),
                       "source": S("string", "Origin, e.g. 'dictation', 'meeting 2 Oct'.")},
                      note_create, Risk.PREPARE, required=["title", "body"],
                      summarize=lambda a: f"save note '{a['title']}'", category="notes"))
    reg.register_undo("note_create", lambda p: _async(notes.delete(p["id"]) or "Note removed."))

    async def note_search(a):
        rows = notes.search(a.get("query") or "", int(a.get("limit") or 8))
        if not rows:
            return "No matching notes."
        return ToolResult("\n\n".join(
            f"[note #{n['id']} | {n['kind']} | {dt.datetime.fromtimestamp(n['created_at']):%Y-%m-%d %H:%M}] "
            f"{n['title']}\n{n['body'][:1500]}" for n in rows), sources=[f"note:{n['id']}" for n in rows])
    reg.register(Tool("search_notes", "Search notes by words (empty query = most recent notes).",
                      {"query": S("string", "Search words."), "limit": S("integer", "Max results.")},
                      note_search, required=[], category="notes"))

    async def note_append(a):
        return "Appended." if notes.append(int(a["note_id"]), a["text"]) else "No such note."
    reg.register(Tool("append_to_note", "Add text to the end of an existing note.",
                      {"note_id": S("integer", "Note id."), "text": S("string", "Text to add.")},
                      note_append, Risk.PREPARE, category="notes"))

    # ---------------- tasks / reminders / schedules ----------------
    async def task_create(a):
        due = parse_when(a.get("due"))
        payload = {"prompt": a["prompt"]} if a.get("prompt") else None
        tid = tasks.create(a["title"], description=a.get("description") or "", due_at=due,
                           kind=a.get("kind") or ("reminder" if due and not a.get("project") else "task"),
                           recurrence=a.get("recurrence") or None, priority=a.get("priority") or "normal",
                           project=a.get("project"), source=a.get("source") or "user", payload=payload)
        return ToolResult(f"Created {TaskStore.fmt(tasks.get(tid))}", undo=("task_create", {"id": tid}))
    reg.register(Tool(
        "create_task",
        "Create a task, reminder or scheduled job. kind: task (to-do, optionally with deadline), reminder "
        "(spoken at due time), agent (at due time JARVIS runs `prompt` as if the user asked it, e.g. "
        "'summarize my week'), briefing (daily briefing). Use recurrence for repeating items.",
        {"title": S("string", "Short title."), "description": S("string", "Details."),
         "due": S("string", "ISO 8601 local datetime, e.g. 2026-10-03T09:00. Compute from the current time."),
         "kind": S("string", "task | reminder | agent | briefing"),
         "recurrence": S("string", "Optional repeat.", enum=list(RECURRENCES)),
         "priority": S("string", "low | normal | high"), "project": S("string", "Project name."),
         "prompt": S("string", "For kind=agent: the instruction to run at due time."),
         "source": S("string", "Origin, e.g. 'meeting 2 Oct', 'email from John'.")},
        task_create, Risk.PREPARE, required=["title"], summarize=lambda a: f"create task '{a['title']}'",
        category="tasks"))
    reg.register_undo("task_create", lambda p: _async(tasks.cancel(p["id"]) and "Task removed."))

    async def task_list(a):
        rows = tasks.open_tasks(int(a.get("limit") or 30), a.get("kind"))
        return "\n".join(TaskStore.fmt(t) for t in rows) or "No open tasks."
    reg.register(Tool("list_tasks", "List open tasks, reminders and scheduled jobs.",
                      {"kind": S("string", "Optional filter: task | reminder | agent | briefing"),
                       "limit": S("integer", "Max results.")}, task_list, required=[], category="tasks"))

    async def task_done(a):
        tid = int(a["task_id"])
        ok = tasks.complete(tid)
        return ToolResult("Marked done." if ok else "No open task with that id.",
                          undo=("task_reopen", {"id": tid}) if ok else None)
    reg.register(Tool("complete_task", "Mark a task as done.", {"task_id": S("integer", "Task id.")},
                      task_done, Risk.PREPARE, category="tasks"))
    reg.register_undo("task_reopen", lambda p: _async(tasks.reopen(p["id"]) or "Task reopened."))

    async def task_cancel(a):
        ok = tasks.cancel(int(a["task_id"]))
        return ToolResult("Cancelled." if ok else "No such task.", undo=("task_reopen", {"id": int(a["task_id"])}))
    reg.register(Tool("cancel_task", "Cancel a task, reminder or recurring job.", {"task_id": S("integer", "Task id.")},
                      task_cancel, Risk.PREPARE, category="tasks"))

    # ---------------- contacts ----------------
    async def contact_save(a):
        fields = {k: a.get(k) for k in contacts.FIELDS}
        cid = contacts.upsert(a["name"], a.get("source") or "user", **fields)
        return f"Saved contact #{cid}."
    reg.register(Tool("save_contact", "Create or update a person in the contact book. Only store real information "
                      "you were given; never invent details.",
                      {"name": S("string", "Full name."), "organization": S("string", ""), "role": S("string", ""),
                       "email": S("string", ""), "phone": S("string", ""),
                       "relationship": S("string", "How the user knows them."),
                       "notes": S("string", "Context, recent interactions, preferences."),
                       "source": S("string", "Where this came from.")},
                      contact_save, Risk.PREPARE, required=["name"], category="contacts"))

    async def contact_find(a):
        rows = contacts.find(a["query"])
        if not rows:
            return "No contact found. Don't invent details; you could search emails instead."
        return ToolResult("\n".join(
            f"[contact #{c['id']} | source: {c['source']}] {c['name']} | org: {c['organization'] or '-'} | "
            f"role: {c['role'] or '-'} | email: {c['email'] or '-'} | phone: {c['phone'] or '-'} | "
            f"relationship: {c['relationship'] or '-'} | notes: {c['notes'] or '-'}" for c in rows),
            sources=[f"contact:{c['id']}" for c in rows])
    reg.register(Tool("find_contact", "Look up a person by name, email or organization.",
                      {"query": S("string", "Name, email or company.")}, contact_find, category="contacts"))

    # ---------------- provenance / activity / undo ----------------
    async def explain(a):
        run = svc.tracer.last_completed_run(before=reg.current_run)
        if a.get("run_id"):
            run = int(a["run_id"])
        return svc.tracer.explain(run) if run else "I have no previous request on record."
    reg.register(Tool("explain_previous_answer",
                      "Show exactly how the previous answer was produced: tools, sources, models, approvals. "
                      "Use for 'who told you that?', 'how did you get that?', 'where is that from?'.",
                      {"run_id": S("integer", "Optional specific run id.")}, explain, required=[], category="trace"))

    async def activity(a):
        m = svc.tracer.metrics()
        rows = svc.tracer.recent_activity(int(a.get("limit") or 15))
        lines = [f"{dt.datetime.fromtimestamp(r['ts']):%H:%M:%S} {r['kind']} {r['name']} {r['status'] or ''}"
                 for r in rows]
        return f"Metrics: {m}\nRecent:\n" + "\n".join(lines)
    reg.register(Tool("recent_activity", "Recent actions JARVIS took, plus success/error metrics.",
                      {"limit": S("integer", "How many entries.")}, activity, required=[], category="trace"))

    async def undo(a):
        return await reg.undo_last()
    reg.register(Tool("undo_last_action", "Undo the most recent reversible action (note, task, memory, file move, "
                      "calendar event, archive...).", {}, undo, Risk.LOCAL, category="trace"))

    # ---------------- settings ----------------
    async def get_settings(a):
        s = svc.settings.public()
        s["trust_level_name"] = TRUST_NAMES[svc.settings.trust_level]
        return str(s)
    reg.register(Tool("get_settings", "Show JARVIS settings (trust level, voice, proactivity, briefing time...).",
                      {}, get_settings, category="settings"))

    async def set_setting(a):
        key, value = a["key"], a["value"]
        allowed = {"trust_level": int, "proactive": lambda v: str(v).lower() in ("true", "1", "yes", "on"),
                   "briefing_time": str, "follow_up_seconds": float, "user_name": str, "voice": str,
                   "model_fast": str, "model_reasoning": str, "wake_sensitivity": float}
        if key not in allowed:
            return ToolResult(f"Setting {key} can't be changed by voice. Allowed: {list(allowed)}", is_error=True)
        old = getattr(svc.settings, key)
        setattr(svc.settings, key, allowed[key](value))
        svc.settings.save()
        svc.bus.publish("settings.changed", key=key, value=getattr(svc.settings, key))
        return f"{key} changed from {old} to {getattr(svc.settings, key)}."
    reg.register(Tool("change_setting", "Change a JARVIS setting. Changing permissions (trust_level) always needs the "
                      "user's approval.",
                      {"key": S("string", "Setting name."), "value": S("string", "New value.")},
                      set_setting, Risk.DANGEROUS, summarize=lambda a: f"change setting {a['key']} to {a['value']}",
                      category="settings"))


def _async(value):
    async def _f():
        return value if isinstance(value, str) else "Done."
    return _f()
