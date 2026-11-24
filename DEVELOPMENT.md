# Development

```
cd jarvis
.venv\Scripts\activate
pip install -r requirements.txt

python -m pytest tests -q          # 41 tests: unit, integration, agent loop with mocks
python -m jarvis_os --mock --text  # no Claude, no Google, no real mouse/keyboard
python -m jarvis_os --text         # real Claude, type instead of talking
python -m jarvis_os                # full voice + UI  (same as jarvis.py / desktop shortcut)
```

## Mock switches (`.env`)
`JARVIS_MOCK_LLM`, `JARVIS_MOCK_EMAIL`, `JARVIS_MOCK_CALENDAR` and `JARVIS_MOCK_COMPUTER`. Setting `--mock` turns on all four.

## Layout
```
jarvis_os/
  __main__.py      entry point (voice+UI, --text, --mock)
  app.py           conversation controller (wake, follow-up, barge-in, privacy, notifications)
  config.py        env + settings.json
  services.py      dependency container
  core/            db (migrations), events, trace
  agent/           orchestrator, router, providers, prompts
  tools/           registry + tool modules
  safety/          policy, approval
  memory/          memories, notes, contacts
  tasks/           task store, scheduler/proactive
  connectors/      email/calendar adapters (Google, mock)
  computer/        computer-control adapters (Windows, mock)
  voice/           audio engine, STT, TTS, hotkey, VoiceIO
  ui/              Tk window
tests/
data/              jarvis.db, settings.json   (created at runtime; private)
```

## Troubleshooting
- **It doesn't react to "Hey Jarvis".** Check the console line `[audio] wake word (0.xx)`. Lower `wake_sensitivity` in `data/settings.json` (the default is 0.5).
- **It hears you but doesn't understand.** Your mic is very quiet. The recording is boosted up to 40×, but sitting closer helps.
- **Gmail or Calendar errors.** Delete `token.json` and sign in again.
