"""Database, events, memory, notes, contacts, tasks."""
import datetime as dt

from conftest import run  # noqa: F401
from jarvis_os.core.db import Database, fts_query
from jarvis_os.core.events import EventBus
from jarvis_os.tasks.store import next_occurrence


def test_migrations_idempotent(tmp_path):
    db = Database(tmp_path / "a.db")
    v = db.version
    db.migrate()
    assert db.version == v >= 1


def test_event_bus_wildcards():
    bus, got = EventBus(), []
    bus.subscribe("tool.*", lambda e: got.append(("prefix", e.type)))
    bus.subscribe("*", lambda e: got.append(("all", e.type)))
    bus.subscribe("tool.started", lambda e: 1 / 0)          # broken subscriber must not break publish
    bus.publish("tool.started", tool="x")
    assert ("prefix", "tool.started") in got and ("all", "tool.started") in got


def test_fts_query_is_safe():
    q = fts_query('what did "John" say about the contract) OR *')
    assert '"john"*' in q and '"contract"*' in q and ")" not in q


def test_memory_store_search_dedupe_privacy(svc):
    m = svc.memory
    i1, _ = m.add("The client wants the presentation by Thursday", "project", "user said", 0.8)
    i2, msg = m.add("the client wants the presentation by thursday", "project", "user said")
    assert i1 == i2 and "Already" in msg
    m.add("User prefers short emails", "preference", "user said", 0.9)
    hits = m.search("when is the presentation due")
    assert hits and hits[0]["id"] == i1
    assert any("short emails" in p["content"] for p in m.profile())
    m.paused = True
    assert m.add("secret", "fact", "x")[0] is None
    m.paused = False
    assert m.forget(i1) and not m.search("presentation")


def test_notes_and_contacts(svc):
    nid = svc.notes.create("Pricing", "Acme wants a 10% discount", "meeting", "acme")
    assert svc.notes.search("discount")[0]["id"] == nid
    cid = svc.contacts.upsert("Sarah Mitchell", organization="Acme", email="sarah@acme.example")
    assert svc.contacts.upsert("sarah mitchell", role="CFO") == cid
    c = svc.contacts.find("acme")[0]
    assert c["role"] == "CFO" and c["organization"] == "Acme"


def test_tasks_due_and_recurrence(svc):
    t = svc.tasks
    past = (dt.datetime.now() - dt.timedelta(minutes=1)).timestamp()
    rid = t.create("Call mom", due_at=past, kind="reminder")
    bid = t.create("Briefing", due_at=past, kind="briefing", recurrence="daily")
    plain = t.create("Proposal", due_at=past, kind="task")
    due_ids = {x["id"] for x in t.due()}
    assert {rid, bid, plain} <= due_ids
    for x in t.due():
        t.mark_fired(x)
    assert t.due() == []
    assert t.get(rid)["status"] == "done"
    assert t.get(bid)["status"] == "open" and t.get(bid)["due_at"] > past
    assert t.get(plain)["status"] == "open"


def test_next_occurrence_weekdays():
    fri = dt.datetime(2026, 10, 2, 8, 0).timestamp()      # a Friday
    assert dt.datetime.fromtimestamp(next_occurrence(fri, "weekdays")).weekday() == 0
