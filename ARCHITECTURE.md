# JARVIS architecture

JARVIS is a voice-first personal agent that runs on your Windows PC. Claude is the brain, and it uses your Claude.ai subscription through the Claude Agent SDK. Every action goes through one audited, permission-checked tool path.

## The loop

```
mic ─▶ wake word / hotkey ─▶ record (VAD) ─▶ STT ─▶ App controller ─┬─ local commands (stop, privacy, quit…)
                                                                    └─▶ Orchestrator
Orchestrator: route (router.py) ─▶ context (memories, due tasks) ─▶ Claude (Agent SDK, streamed)
     │                                                                  │ tool calls
     │                                                                  ▼
     │                         ToolRegistry.execute: policy ─▶ approval ─▶ handler (timeout/retry)
     │                                             ─▶ trace + provenance ─▶ undo record ─▶ events
     ▼
SentenceStream ─▶ Speaker (neural TTS, pipelined, interruptible) ─▶ follow-up listening
```

## Components

| # | Component | Where | Notes |
|---|-----------|-------|-------|
| 1 | Voice interface | `voice/audio.py`, `stt.py`, `speaker.py`, `io.py`, `hotkey.py` | One mic stream broadcast to listeners. Offline "hey jarvis" wake word (openWakeWord), Silero VAD, Google STT, edge-tts. Global hotkey uses Win32 `RegisterHotKey`. |
| 2 | Agent orchestrator | `agent/orchestrator.py` | `ClaudeAgent` (real) and `MockAgent` (tests). Streams sentences to speech, traces built-in web tools, and supports interrupt. |
| 3 | Planner | inside the Claude agent loop | Planning happens in the model; the prompt enforces observe → act → verify. A separate planner agent is still on the roadmap. |
| 4 | Tool registry | `tools/registry.py` | `Tool` has a name, description, JSON schema, risk, timeout, retries, a summary for approvals, and a category. `ToolResult` carries text, an image, sources and undo information. |
| 5 | Computer control | `computer/controller.py` | Abstract `ComputerController`. `WindowsController` uses pyautogui, PIL and pygetwindow, is multi-monitor and DPI-aware. `MockController` is for tests. |
| 6 | Browser | `open_url`, `play_on_youtube`, Claude `WebSearch`/`WebFetch`, plus UI control | No Playwright agent yet. |
| 7 | Communication | `connectors/` | `EmailAdapter`, `CalendarAdapter` and `CallAdapter` interfaces, with Gmail/Google Calendar and mock implementations. |
| 8 | Memory | `memory/store.py` | Structured memories (category, source, confidence, importance, timestamps) with FTS5 search plus importance/recency ranking. |
| 9 | Knowledge / RAG | `read_file`, `search_files`, notes FTS | Folder indexing and embeddings are on the roadmap. |
| 10 | Model router | `agent/router.py`, `agent/providers.py` | Routes to fast or reasoning models. `ModelProvider` has Claude, OpenAI (optional) and mock implementations. |
| 11 | Approval and safety | `safety/policy.py`, `safety/approval.py` | Risk classes × trust levels. Approval comes from voice or the UI card, whichever answers first, with a timeout that denies. Untrusted-content wrapping. |
| 12 | Task manager | `tasks/store.py` | Tasks, reminders, scheduled agent jobs, recurrence. |
| 13 | Event system | `core/events.py` | In-process pub/sub with wildcard subscriptions. |
| 14 | Notifications | `tasks/scheduler.py` → app | Spoken, chime and activity panel. |
| 15 | Observability | `core/trace.py` | `runs` and `trace` tables, plus metrics: success rate, tool errors, latency, approvals. |
| 16 | UI | `ui/window.py` | Orb with 11 states, activity panel, approval card, compact always-on-top mode. |
| 17 | Settings | `config.py` → `data/settings.json` | Can also be changed by voice through `change_setting`, which always needs approval. |
| 18 | Audit log | `trace`, `approvals` and `actions` tables | Every tool call, approval and reversible action is logged. |

## Data

All data lives in a single SQLite file, `data/jarvis.db`, using WAL mode and numbered migrations (`core/db.py`). It holds these tables: memories (+FTS), notes (+FTS), tasks, contacts, runs, trace, approvals, actions (undo log) and meetings. A database server would be unnecessary infrastructure for a single-user desktop agent.

## Key decisions

- **Python, single process.** Audio, wake word, Windows automation and the Agent SDK are all strongest in Python. The UI is Tk for now: it has no build step and is event-driven. A Tauri/Electron command center can later sit on top of the same event bus over a WebSocket bridge (Phase 12).
- **Claude through the Agent SDK, not the API.** The user wants their Claude.ai subscription, and the SDK gives streaming, interrupt, set_model per request, and MCP-style in-process tools. Other providers only plug in for consultation, and the system never claims a provider was used when it wasn't.
- **One tool path.** Policy, approval, timeout, trace, undo and events all live in `ToolRegistry.execute`, so no tool can skip them.
- **Volume-independent VAD.** The user's headset microphone is very quiet. Energy thresholds failed, so speech detection uses Silero instead.
- **External content is data.** Email, file and web text is wrapped in `<untrusted_content>` tags, and the system prompt forbids following instructions found inside them.

## Roadmap and status

| Phase | Status |
|---|---|
| 1 Foundation (config, DB, events, trace) | ✅ done, tested |
| 2 Orchestrator (streaming, routing, context, interrupt) | ✅ done, tested (mock), verified live |
| 3 Tool system (registry, policy, approval, undo) | ✅ done, tested |
| 4 Voice (wake word, VAD, STT, TTS, barge-in, hotkey, dictation) | ✅ done. Wake and STT verified on the user's mic; the full voice loop needs user testing |
| 5 Computer control (multi-monitor, verify loop) | ✅ done, verified live (Notepad slice) |
| 6 Memory / notes / tasks / contacts | ✅ done, tested. Embedding search not done |
| 7 Email / calendar | ✅ adapters + tools done and tested on mocks. Live Gmail needs the user's Google sign-in |
| 8 Browser agent (Playwright) | ⏳ not started. Uses web search/fetch plus UI control for now |
| 9 Meetings | ✅ continuous timestamped transcription and summary flow. No speaker diarization (the free STT can't do it) |
| 10 Multi-model | ✅ router + consult_model. OpenAI only works when `OPENAI_API_KEY` is set |
| 11 Proactive | ✅ reminders, scheduled jobs, daily briefing, calendar heads-ups |
| 12 Premium UI | 🟡 Tk command orb + activity + approvals. Full multi-section command center (Tauri) not started |
| 13 Security hardening | 🟡 policy, untrusted wrapping, path guard, redaction done. Credential encryption (Windows DPAPI) not done |
| 14 Testing | 🟡 41 unit/integration tests. No UI automation tests |
| 15 Packaging | 🟡 desktop and startup shortcuts. No installer |
