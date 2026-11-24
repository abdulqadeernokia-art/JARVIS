# Memory

## Structured memories (`memories` table)
Each memory stores its content, category, source, timestamps (`created_at`, `updated_at`, `last_used`), confidence, importance, and whether it's still active.

The categories are: identity, preference, person, project, decision, fact, habit and conversation.

- **What gets written:** the agent decides. The system prompt tells it to store preferences, people, projects, decisions, deadlines and lasting facts, and never trivia or secrets.
- **Duplicates:** if the same text is stored again, the existing memory is refreshed instead of duplicated.
- **Corrections:** `update_memory` changes a memory and `forget_memory` deactivates it. Both can be undone.
- **Search:** full-text search (FTS5, prefix match on keywords), then re-ranked by `relevance + 2×importance + recency`.
- **Context injection:** every request automatically includes identity and preference memories plus the six most relevant memories, each labelled with its id and source. The agent has to cite the source and must never claim to remember anything that isn't stored.
- **Privacy mode:** `MemoryStore.paused` blocks all new writes.

## Notes, tasks, contacts, meetings
- **Notes:** full-text search, with kinds quick, meeting, project, voice and briefing, plus tags.
- **Tasks:** these are also the scheduler's job queue: reminders, `agent` prompts, and the daily briefing, with recurrence.
- **Contacts:** names, contact details, relationship and notes. Each contact records its source, and no details are ever invented.
- **Meetings:** timestamped transcript segments. The summary is saved as a note of kind `meeting`.

## Not yet
- Embedding-based semantic search (needs a local embedding model or an embeddings API)
- Automatic staleness decay
- Indexing your folders for "what does my documentation say about…"
