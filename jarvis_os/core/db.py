"""SQLite database with numbered migrations. One file, no server, full-text search via FTS5."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

MIGRATIONS: list[str] = [
    # 1: core tables
    """
    CREATE TABLE memories (
        id INTEGER PRIMARY KEY, content TEXT NOT NULL, category TEXT NOT NULL,
        source TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
        confidence REAL NOT NULL DEFAULT 1.0, importance REAL NOT NULL DEFAULT 0.5,
        last_used REAL, active INTEGER NOT NULL DEFAULT 1
    );
    CREATE VIRTUAL TABLE memories_fts USING fts5(content, category, content='memories', content_rowid='id');
    CREATE TRIGGER memories_ai AFTER INSERT ON memories BEGIN
        INSERT INTO memories_fts(rowid, content, category) VALUES (new.id, new.content, new.category); END;
    CREATE TRIGGER memories_ad AFTER DELETE ON memories BEGIN
        INSERT INTO memories_fts(memories_fts, rowid, content, category) VALUES ('delete', old.id, old.content, old.category); END;
    CREATE TRIGGER memories_au AFTER UPDATE ON memories BEGIN
        INSERT INTO memories_fts(memories_fts, rowid, content, category) VALUES ('delete', old.id, old.content, old.category);
        INSERT INTO memories_fts(rowid, content, category) VALUES (new.id, new.content, new.category); END;

    CREATE TABLE notes (
        id INTEGER PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'quick',
        tags TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'user', created_at REAL NOT NULL,
        updated_at REAL NOT NULL, deleted INTEGER NOT NULL DEFAULT 0
    );
    CREATE VIRTUAL TABLE notes_fts USING fts5(title, body, tags, content='notes', content_rowid='id');
    CREATE TRIGGER notes_ai AFTER INSERT ON notes BEGIN
        INSERT INTO notes_fts(rowid, title, body, tags) VALUES (new.id, new.title, new.body, new.tags); END;
    CREATE TRIGGER notes_ad AFTER DELETE ON notes BEGIN
        INSERT INTO notes_fts(notes_fts, rowid, title, body, tags) VALUES ('delete', old.id, old.title, old.body, old.tags); END;
    CREATE TRIGGER notes_au AFTER UPDATE ON notes BEGIN
        INSERT INTO notes_fts(notes_fts, rowid, title, body, tags) VALUES ('delete', old.id, old.title, old.body, old.tags);
        INSERT INTO notes_fts(rowid, title, body, tags) VALUES (new.id, new.title, new.body, new.tags); END;

    CREATE TABLE tasks (
        id INTEGER PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'open', priority TEXT NOT NULL DEFAULT 'normal',
        kind TEXT NOT NULL DEFAULT 'task', due_at REAL, recurrence TEXT, project TEXT,
        source TEXT NOT NULL DEFAULT 'user', payload TEXT NOT NULL DEFAULT '{}',
        created_at REAL NOT NULL, updated_at REAL NOT NULL, completed_at REAL, fired_at REAL
    );
    CREATE INDEX tasks_due ON tasks(status, due_at);

    CREATE TABLE contacts (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, organization TEXT, role TEXT, email TEXT, phone TEXT,
        relationship TEXT, notes TEXT, source TEXT NOT NULL DEFAULT 'user',
        created_at REAL NOT NULL, updated_at REAL NOT NULL
    );

    CREATE TABLE runs (
        id INTEGER PRIMARY KEY, started_at REAL NOT NULL, ended_at REAL, input TEXT NOT NULL,
        output TEXT, status TEXT NOT NULL DEFAULT 'running', model TEXT, route TEXT, channel TEXT
    );
    CREATE TABLE trace (
        id INTEGER PRIMARY KEY, run_id INTEGER, ts REAL NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL,
        risk TEXT, status TEXT, latency_ms INTEGER, detail TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX trace_run ON trace(run_id);

    CREATE TABLE approvals (
        id INTEGER PRIMARY KEY, run_id INTEGER, ts REAL NOT NULL, tool TEXT NOT NULL, summary TEXT NOT NULL,
        decision TEXT, decided_by TEXT, decided_at REAL
    );

    CREATE TABLE actions (
        id INTEGER PRIMARY KEY, run_id INTEGER, ts REAL NOT NULL, tool TEXT NOT NULL, description TEXT NOT NULL,
        undo_kind TEXT, undo_payload TEXT, undone INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE meetings (
        id INTEGER PRIMARY KEY, title TEXT NOT NULL, started_at REAL NOT NULL, ended_at REAL,
        segments TEXT NOT NULL DEFAULT '[]', summary_note_id INTEGER
    );
    """,
]


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._lock = threading.RLock()
        self.migrate()

    def migrate(self) -> None:
        with self._lock:
            self._conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
            row = self._conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
            current = row[0] or 0
            for i, sql in enumerate(MIGRATIONS[current:], start=current + 1):
                self._conn.executescript("BEGIN;" + sql + f"; INSERT INTO schema_version VALUES ({i}); COMMIT;")

    @property
    def version(self) -> int:
        return self.query_one("SELECT MAX(version) AS v FROM schema_version")["v"]

    def execute(self, sql: str, params: tuple | dict = ()) -> int:
        with self._lock:
            cur = self._conn.execute(sql, params)
            return cur.lastrowid if cur.lastrowid else cur.rowcount

    def query(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def now() -> float:
    return time.time()


def dumps(obj: Any) -> str:
    return json.dumps(obj, default=str, ensure_ascii=False)


def fts_query(text: str) -> str:
    """Turn free text into a safe FTS5 OR-query (prefix matching, no syntax injection)."""
    import re
    stop = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "was", "what", "did",
            "do", "i", "me", "my", "we", "you", "about", "that", "this", "it", "with", "when", "remember"}
    words = [w for w in re.findall(r"[\w']+", text.lower()) if w not in stop and len(w) > 1]
    return " OR ".join(f'"{w.replace(chr(34), "")}"*' for w in words[:12])
