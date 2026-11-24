# Tools

Every tool is a `Tool(name, description, params, handler, risk, timeout, retries, summarize, category)` (see `jarvis_os/tools/registry.py`). Every tool runs through `ToolRegistry.execute`, which handles permissions, approval, timeout and retry, the activity trace with sources, undo, and events.

| Category | Tools (risk) |
|---|---|
| time | get_current_datetime (R) |
| memory | remember (P), recall (R), update_memory (P), forget_memory (P) |
| notes | create_note (P), search_notes (R), append_to_note (P) |
| tasks | create_task (P): task/reminder/agent/briefing, with recurrence; list_tasks (R), complete_task (P), cancel_task (P) |
| contacts | save_contact (P), find_contact (R) |
| trace | explain_previous_answer (R): "who told you?"; recent_activity (R); undo_last_action (L) |
| settings | get_settings (R), change_setting (D) |
| email | search_email (R), read_email (R), draft_email (P), delete_draft (P), **send_draft (E)**, archive_email (L), mark_email (L), label_email (L) |
| calendar | list_calendar_events (R), **create_calendar_event (E)** |
| computer | screenshot (R, multi-monitor), list_windows (R), click / move_mouse / drag / type_text / press_keys / scroll (L), focus_window / window_action (L), read_clipboard (R), copy_to_clipboard (L), open_application (L) |
| browser/media | open_url (L), play_on_youtube (L), media_control (L), system_status (R), lock_computer (L), plus Claude's built-in WebSearch / WebFetch |
| files | list_folder (R), search_files (R), read_file (R, txt/md/csv/code/pdf), create_file (L), move_file (L), create_folder (L), **delete_to_recycle_bin (D)** |
| voice | dictate (R): clean or verbatim; start_meeting_mode / stop_meeting_mode (P), meeting_transcript_so_far (R), get_meeting_transcript (R) |
| ai | consult_model (R): independent opinions from available providers |

Risk letters: R = READ, P = PREPARE, L = LOCAL, E = EXTERNAL, D = DANGEROUS.

**Undo** is supported for: notes, tasks, memories (forget and restore), drafts, archived email, calendar events, file moves, created files (sent to the Recycle Bin) and created folders.

## Adding a tool

```python
reg.register(Tool("my_tool", "What it does and when to use it.",
                  {"arg": S("string", "meaning")}, handler, Risk.LOCAL,
                  summarize=lambda a: f"do X to {a['arg']}",   # shown in approvals and the activity log
                  category="mine"))
```

Return a `ToolResult(text, sources=[...], undo=("kind", payload))` and register an undo handler with `reg.register_undo("kind", fn)`. Put the tool in a module under `jarvis_os/tools/` and add that module to `load_all`.
