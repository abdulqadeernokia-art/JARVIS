# JARVIS

JARVIS is a voice-first personal AI agent for your Windows PC. It runs on your Claude.ai subscription, so you don't need an API key.

He listens for **"Hey Jarvis"**. He can:
- see your screens and operate apps
- handle email and your calendar
- take notes and dictation
- transcribe meetings
- remember things you tell him
- run reminders and a daily briefing
- research on the web
- tell you exactly where each answer came from

## Start

Double-click **JARVIS** on the Desktop. He also starts automatically when you log in.


## Conversation mode (hands-free)

Talk to JARVIS back and forth with no wake word or buttons between turns.

**Start:** say "Jarvis, let's talk" (or "conversation mode"), click **◎ Talk** in the top bar, or launch with
`python -m jarvis_os --converse`.
**Stop:** say "stop conversation" or "goodbye", click **◉ Talking**, or stay quiet for 30 seconds. JARVIS then goes
back to waiting for "Jarvis".
You can talk over him at any time. He stops mid-sentence, drops the rest of his reply, and listens to you.

How it works (`jarvis_os/conversation/`), all stages streaming and connected by asyncio queues:
sounddevice mic (16 kHz, 32 ms frames) → Silero VAD (turn ends after 700 ms of silence) → faster-whisper STT
(starts speculatively after 250 ms of silence) → brain (streamed tokens) → sentence chunker (the first phrase goes
early) → TTS → gapless playback queue. States: IDLE, LISTENING, THINKING, SPEAKING, INTERRUPTED. While he speaks,
the VAD needs a stronger and longer signal before it counts as a barge-in, so he doesn't hear himself.
A headset is best because there is no acoustic echo cancellation.

| File | Role |
|---|---|
| `config.py` | All settings, from `.env` (see `.env.example`, "Conversation mode") |
| `brains.py` | `Brain` interface: `ClaudeSDKBrain` (default, Claude.ai login), `ClaudeAPIBrain`, `OllamaBrain` |
| `speech.py` | `SpeechToText` (faster-whisper, Google) and `TextToSpeech` (Piper, edge-tts, ElevenLabs) |
| `audio.py` | Mic capture, Silero VAD, interruptible player |
| `session.py` | The pipeline, state machine, barge-in, rolling memory (last 12 turns), latency log |

**Setup:** `pip install -r requirements.txt`. For the local Piper voice, put
`en_GB-alan-medium.onnx` and `.onnx.json` from
https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_GB/alan/medium in `data/models/piper/`. Without it,
edge-tts is used, which is about 1–2 s slower per sentence. The Whisper model downloads on first use.

**Latency test** (end of speech → first audio out, target < 1.5 s):
```
python -m jarvis_os.conversation.latency_test                 # feeds a recorded question in as the mic
python -m jarvis_os.conversation.latency_test --live          # talk yourself
python -m jarvis_os.conversation.latency_test --brain ollama  # compare brains / --tts / --stt
```
Each turn also logs a line like `lat speech end → detected 703 · stt 719 · first token … · FIRST AUDIO OUT … ms`.

In conversation mode the brain has no tools. For actions (email, apps, files), say "stop conversation" and ask
normally.

## Window buttons

The galaxy window opens full screen with no title bar, so its controls are in the top-right of the HUD:
**—** minimises it, and **✕** (click twice) exits JARVIS. After exiting, he still wakes when you say "Jarvis".
**Shift+✕** quits completely.

## The Galaxy interface (default UI)

`python -m jarvis_os` now opens JARVIS as a full-screen 3D universe in an Edge/Chrome app window. It shows a
spiral galaxy, nebulae, the AI core and nine planets. The core's animation follows real state (idle, listening,
thinking, speaking, executing, approval, error, privacy). It reacts to your actual microphone level and to
JARVIS's speech envelope, which comes from TTS word timings.

| Key | Action |
|---|---|
| 1–9 | Fly to a planet (Google, YouTube, Communication, AI, Computer, Research, Personal Life, Smart Home, Settings) |
| Esc / H | Interrupt if busy, otherwise return to the galaxy |
| / | Type a message · Ctrl+Space: talk · F: full screen · Ctrl+Shift+X: **emergency stop** |
| Mouse | Drag to rotate, wheel to zoom, click a planet to travel, click the core to talk |

Options: `--classic` (old Tk orb), `--no-mic` (typed only), `--no-window`, `--port N`.

**Rebuilding the UI** (Node.js LTS is installed): `cd galaxy && npm install && npm run build`. For UI development, run
`python -m jarvis_os --no-window` and `npm run dev`, then open `http://localhost:5173/?token=<token from the log>`.

How it fits together: `galaxy/` (React + Three.js/R3F + Tailwind) talks over a WebSocket to `jarvis_os/bridge/server.py`.
The server listens on 127.0.0.1 only, needs a per-session token, and rejects foreign origins. Every command it
accepts is allow-listed. Tool calls from the UI go through the same policy → approval → audit path the agent uses.
To add a planet, add an entry in `galaxy/src/lib/planets.ts` and a panel in `galaxy/src/ui/panels/`.

What each optional service needs:
- **API keys**: Settings planet → Keys. They're encrypted with Windows DPAPI in `data/secrets.bin` and never shown again.
  Claude needs no key (it uses your Claude Code login). OpenAI needs a paid key from platform.openai.com.
- **Gmail and Calendar**: `credentials.json` (see Setup below).
- **Smart Home**: a running Home Assistant plus a long-lived token, entered on the Smart Home planet.
- **Wake word**: the offline model only knows "Hey Jarvis". A custom wake word would need a newly trained
  openWakeWord model.

## Talking to him

| Do this | Say or press |
|---|---|
| Wake him | "Hey Jarvis" · **Ctrl+Alt+J** · click the orb |
| Interrupt him | "Hey Jarvis" while he's talking or working, then "stop", or give a correction |
| Follow up | Just keep talking. He listens for about 7 seconds after each answer. |
| Send him to standby | "That's all" / "Thanks Jarvis" |
| Privacy mode | "Privacy mode". He stops listening and remembering. Press the hotkey or click the orb to resume. |
| Start over | "New conversation" |
| Shut him down | "Jarvis, shut down", or right-click the orb → Shut down. Closing the window only minimizes it. |
| Floating mini mode | Double-click the orb (or press F11) |

## Things to try

- "What's on my screen?" · "Open Notepad and write a shopping list" · "Close Spotify"
- "Which emails need my attention?" · "Reply to Sarah and say Friday works. Don't send it yet." · "Send it."
- "What's on my calendar tomorrow?" · "Book an hour for deep work at 3 tomorrow"
- "Write this email to John." *(dictate, then say "end dictation")* · "Write exactly what I'm saying into a note"
- "Start meeting mode" … "Stop meeting mode". He saves a summary with decisions, action items and timestamps.
- "Remember that the client wants the presentation by Thursday" · "What did I promise Sarah?"
- "Remind me in 20 minutes to call mom" · "Every Friday at 5, summarize my week"
- "Research Acme and tell me if they're worth partnering with. Get a second opinion."
- "Who told you that?" · "Undo that" · "Organize my Downloads folder" (he shows you the plan first)
- "Play some lo-fi on YouTube" · "Volume down" · "Lock the computer"

## Safety

- Sending email, inviting people and deleting files need your **"yes"**, either spoken or by clicking Approve on the card.
- Your trust level is 2 out of 4 (see [SECURITY.md](SECURITY.md)).
- Email, web and file content is treated as data, never as commands.
- To stop any automation instantly, move the mouse into a screen corner.

## Setup (already done on this PC)

1. Install Python 3.12, then run `pip install -r requirements.txt` inside `.venv`.
2. Log in to Claude Code once (`claude`). JARVIS uses that login.
3. Google: put `credentials.json` (an OAuth client of type **Desktop app**, with the Gmail and Calendar APIs enabled) in this folder. The first time JARVIS uses Gmail or Calendar, a browser window asks you to sign in.

## Docs

- [ARCHITECTURE.md](ARCHITECTURE.md): design and roadmap status
- [SECURITY.md](SECURITY.md)
- [TOOLS.md](TOOLS.md)
- [MEMORY.md](MEMORY.md)
- [MODEL_ROUTING.md](MODEL_ROUTING.md)
- [DEVELOPMENT.md](DEVELOPMENT.md)
- [CONTRIBUTING.md](CONTRIBUTING.md)
