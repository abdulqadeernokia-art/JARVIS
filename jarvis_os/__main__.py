"""Entry point.

  python -m jarvis_os            voice + UI (normal use)
  python -m jarvis_os --text     type instead of speaking (no mic, no UI)
  python -m jarvis_os --classic  voice + the old Tk orb window instead of the 3D galaxy
  python -m jarvis_os --no-mic   galaxy UI with typed input only
  python -m jarvis_os --converse start straight in hands-free conversation mode
  python -m jarvis_os --mock     mock LLM/email/calendar/computer (development)
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import threading


def main() -> None:
    p = argparse.ArgumentParser(prog="jarvis")
    p.add_argument("--text", action="store_true", help="text console instead of voice")
    p.add_argument("--mock", action="store_true", help="mock all external services")
    p.add_argument("--classic", action="store_true", help="Tk orb window instead of the 3D galaxy UI")
    p.add_argument("--no-mic", action="store_true", help="galaxy UI without microphone (typed input only)")
    p.add_argument("--no-window", action="store_true", help="start the galaxy server without opening a window")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--converse", action="store_true", help="start in hands-free conversation mode")
    p.add_argument("--woken", action="store_true", help="started because the supervisor heard 'Jarvis'")
    args = p.parse_args()
    if args.mock:
        for k in ("JARVIS_MOCK_LLM", "JARVIS_MOCK_EMAIL", "JARVIS_MOCK_CALENDAR", "JARVIS_MOCK_COMPUTER"):
            os.environ[k] = "1"
    try:
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    except Exception:
        pass

    from . import config
    from .core import secrets
    secrets.export_env()          # API keys from the encrypted vault -> environment for the SDKs
    from .agent.orchestrator import make_agent
    from .app import JarvisApp, text_console
    from .services import build_services

    svc = build_services()
    agent = make_agent(svc, config.MOCK_LLM)

    if args.text:
        def console_approval(req):
            ans = input(f"\n[APPROVAL] JARVIS wants to: {req.summary}\n{req.preview}\nApprove? [y/N] ")
            return "approved" if ans.strip().lower().startswith("y") else "denied"
        svc.approvals.voice_asker = console_approval
        asyncio.run(text_console(JarvisApp(svc, agent)))
        return

    if not args.classic:
        run_galaxy(svc, agent, args)
        return

    from .ui.window import JarvisWindow
    from .voice.audio import AudioEngine
    from .voice.hotkey import start_hotkey
    from .voice.io import VoiceIO
    from .voice.speaker import Speaker, chime
    from .voice.stt import make_stt

    speaker = Speaker(svc.settings.voice,
                      on_state=lambda speaking, text: svc.bus.publish("speaker", speaking=speaking, text=text))
    audio = AudioEngine(svc.settings.wake_sensitivity)
    voice = VoiceIO(audio, make_stt(), speaker, svc.bus)
    svc.voice = voice
    svc.approvals.voice_asker = voice.ask_approval
    app = JarvisApp(svc, agent, voice, speaker, audio, chime)
    app.start_woken = args.woken
    app.start_conversation = args.converse
    audio.on_wake = app.trigger_wake
    print(f"[jarvis] mic: {audio.device}")
    if not start_hotkey(svc.settings.hotkey, app.trigger_wake):
        print(f"[jarvis] could not register hotkey {svc.settings.hotkey} (in use by another app?)")

    window = JarvisWindow(svc.bus, lambda: audio.level, app.trigger_wake,
                          lambda d: svc.approvals.resolve_pending(d, "ui"), app.request_quit, svc.settings.hotkey,
                          on_quit_completely=lambda: app.request_quit(completely=True))

    def run_loop():
        try:
            asyncio.run(app.main())
        except Exception as e:
            print(f"[jarvis] fatal: {e}")
        finally:
            svc.bus.publish("app.quit")

    threading.Thread(target=run_loop, daemon=True, name="jarvis-main").start()
    window.run()
    audio.close()
    os._exit(app.exit_code)    # 0 = supervisor keeps listening for "Jarvis"; 3 = quit completely


def run_galaxy(svc, agent, args) -> None:
    """Default mode: voice engine + 3D galaxy UI served by the local bridge."""
    from .app import JarvisApp
    from .bridge.server import Bridge, open_window
    speaker = audio = voice = None
    chime_fn = None
    try:
        from .voice.speaker import Speaker, chime
        speaker = Speaker(svc.settings.voice,
                          on_state=lambda speaking, text: svc.bus.publish("speaker", speaking=speaking, text=text))
        chime_fn = chime
    except Exception as e:
        print(f"[jarvis] speech output unavailable: {e}")
    if not args.no_mic:
        try:
            from .voice.audio import AudioEngine
            from .voice.io import VoiceIO
            from .voice.stt import make_stt
            audio = AudioEngine(svc.settings.wake_sensitivity)
            voice = VoiceIO(audio, make_stt(), speaker, svc.bus)
            svc.voice = voice
            svc.approvals.voice_asker = voice.ask_approval
            print(f"[jarvis] mic: {audio.device}")
        except Exception as e:
            print(f"[jarvis] microphone unavailable, typed input only: {e}")
            audio = voice = None
    app = JarvisApp(svc, agent, voice, speaker, audio, chime_fn)
    app.start_woken = args.woken
    app.start_conversation = args.converse
    if audio:
        audio.on_wake = app.trigger_wake
        from .voice.hotkey import start_hotkey
        if not start_hotkey(svc.settings.hotkey, app.trigger_wake):
            print(f"[jarvis] could not register hotkey {svc.settings.hotkey}")
    bridge = Bridge(svc, app, audio, speaker, args.port)
    bridge.start_thread()
    if not args.no_window:
        import time
        time.sleep(0.6)
        open_window(bridge.url)
    else:
        print(f"[jarvis] open {bridge.url}")
    try:
        asyncio.run(app.main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"[jarvis] fatal: {e}")
    finally:
        svc.bus.publish("app.quit")
        if audio:
            audio.close()
        if not args.no_window:
            from .bridge.window import close_windows
            close_windows()
    os._exit(app.exit_code)


if __name__ == "__main__":
    main()
