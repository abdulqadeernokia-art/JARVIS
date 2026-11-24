"""Structured long-term memory, notes and contacts. See MEMORY.md."""
from __future__ import annotations

import datetime as dt
import math

from ..core.db import Database, fts_query, now

CATEGORIES = ("identity", "preference", "person", "project", "decision", "fact", "habit", "conversation")


class MemoryStore:
    def __init__(self, db: Database):
        self.db = db
        self.paused = False    # privacy mode: nothing new is stored

    def add(self, content: str, category: str, source: str, importance: float = 0.5,
            confidence: float = 1.0) -> tuple[int | None, str]:
        content = content.strip()
        if self.paused:
            return None, "Privacy mode is on, so I did not store that."
        if category not in CATEGORIES:
            category = "fact"
        dup = self.db.query_one("SELECT id FROM memories WHERE active=1 AND lower(content)=lower(?)", (content,))
        if dup:
            self.db.execute("UPDATE memories SET updated_at=?, importance=MAX(importance, ?) WHERE id=?",
                            (now(), importance, dup["id"]))
            return dup["id"], "Already remembered; refreshed it."
        mid = self.db.execute(
            "INSERT INTO memories(content, category, source, created_at, updated_at, confidence, importance) "
            "VALUES (?,?,?,?,?,?,?)", (content, category, source, now(), now(), confidence, importance))
        return mid, "Remembered."

    def update(self, memory_id: int, content: str) -> bool:
        return bool(self.db.execute("UPDATE memories SET content=?, updated_at=? WHERE id=? AND active=1",
                                    (content, now(), memory_id)))

    def forget(self, memory_id: int) -> bool:
        return bool(self.db.execute("UPDATE memories SET active=0, updated_at=? WHERE id=?", (now(), memory_id)))

    def restore(self, memory_id: int) -> None:
        self.db.execute("UPDATE memories SET active=1 WHERE id=?", (memory_id,))

    def search(self, query: str, limit: int = 8, category: str | None = None) -> list[dict]:
        q = fts_query(query)
        if not q:
            return []
        sql = ("SELECT m.*, bm25(memories_fts) AS rank FROM memories_fts JOIN memories m ON m.id = memories_fts.rowid "
               "WHERE memories_fts MATCH ? AND m.active=1")
        params: list = [q]
        if category:
            sql += " AND m.category=?"
            params.append(category)
        rows = [dict(r) for r in self.db.query(sql + " ORDER BY rank LIMIT 40", tuple(params))]
        # Re-rank: text relevance (bm25 is negative; lower = better) blended with importance and recency.
        t = now()
        for r in rows:
            age_days = (t - r["updated_at"]) / 86400
            r["score"] = -r["rank"] + 2 * r["importance"] + 1.0 / (1 + math.log1p(age_days))
        rows.sort(key=lambda r: r["score"], reverse=True)
        rows = rows[:limit]
        for r in rows:
            self.db.execute("UPDATE memories SET last_used=? WHERE id=?", (t, r["id"]))
        return rows

    def profile(self, limit: int = 15) -> list[dict]:
        """Always-relevant memories: who the user is and how they like things done."""
        return [dict(r) for r in self.db.query(
            "SELECT * FROM memories WHERE active=1 AND category IN ('identity','preference') "
            "ORDER BY importance DESC, updated_at DESC LIMIT ?", (limit,))]

    def list(self, category: str | None = None, limit: int = 50) -> list[dict]:
        if category:
            rows = self.db.query("SELECT * FROM memories WHERE active=1 AND category=? ORDER BY updated_at DESC LIMIT ?",
                                 (category, limit))
        else:
            rows = self.db.query("SELECT * FROM memories WHERE active=1 ORDER BY updated_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    @staticmethod
    def fmt(m: dict) -> str:
        when = dt.datetime.fromtimestamp(m["created_at"]).strftime("%Y-%m-%d")
        return f"[memory #{m['id']} | {m['category']} | source: {m['source']} | {when}] {m['content']}"


class NoteStore:
    def __init__(self, db: Database):
        self.db = db

    def create(self, title: str, body: str, kind: str = "quick", tags: str = "", source: str = "user") -> int:
        return self.db.execute("INSERT INTO notes(title, body, kind, tags, source, created_at, updated_at) "
                               "VALUES (?,?,?,?,?,?,?)", (title, body, kind, tags, source, now(), now()))

    def append(self, note_id: int, text: str) -> bool:
        return bool(self.db.execute("UPDATE notes SET body = body || char(10) || ?, updated_at=? WHERE id=?",
                                    (text, now(), note_id)))

    def delete(self, note_id: int, deleted: bool = True) -> None:
        self.db.execute("UPDATE notes SET deleted=? WHERE id=?", (1 if deleted else 0, note_id))

    def get(self, note_id: int) -> dict | None:
        r = self.db.query_one("SELECT * FROM notes WHERE id=? AND deleted=0", (note_id,))
        return dict(r) if r else None

    def search(self, query: str, limit: int = 10) -> list[dict]:
        q = fts_query(query)
        if not q:
            return self.recent(limit)
        return [dict(r) for r in self.db.query(
            "SELECT n.* FROM notes_fts JOIN notes n ON n.id = notes_fts.rowid WHERE notes_fts MATCH ? "
            "AND n.deleted=0 ORDER BY bm25(notes_fts) LIMIT ?", (q, limit))]

    def recent(self, limit: int = 10) -> list[dict]:
        return [dict(r) for r in self.db.query(
            "SELECT * FROM notes WHERE deleted=0 ORDER BY updated_at DESC LIMIT ?", (limit,))]


class ContactStore:
    FIELDS = ("organization", "role", "email", "phone", "relationship", "notes")

    def __init__(self, db: Database):
        self.db = db

    def upsert(self, name: str, source: str = "user", **fields) -> int:
        fields = {k: v for k, v in fields.items() if k in self.FIELDS and v}
        row = self.db.query_one("SELECT * FROM contacts WHERE lower(name)=lower(?)", (name,))
        if row:
            if fields:
                if "notes" in fields and row["notes"]:
                    fields["notes"] = row["notes"] + "\n" + fields["notes"]
                sets = ", ".join(f"{k}=?" for k in fields)
                self.db.execute(f"UPDATE contacts SET {sets}, updated_at=? WHERE id=?",
                                (*fields.values(), now(), row["id"]))
            return row["id"]
        cols = ", ".join(["name", "source", "created_at", "updated_at", *fields])
        marks = ", ".join("?" * (4 + len(fields)))
        return self.db.execute(f"INSERT INTO contacts({cols}) VALUES ({marks})",
                               (name, source, now(), now(), *fields.values()))

    def find(self, query: str) -> list[dict]:
        like = f"%{query.strip()}%"
        return [dict(r) for r in self.db.query(
            "SELECT * FROM contacts WHERE name LIKE ? OR email LIKE ? OR organization LIKE ? LIMIT 10",
            (like, like, like))]
