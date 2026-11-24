"""Galaxy bridge: a local WebSocket + static server connecting the 3D UI (galaxy/) to the JARVIS core.

- Listens on 127.0.0.1 only, so other machines on your network can't reach it.
- Each session needs a random token. The launcher puts it in the URL it opens, and requests without it are rejected.
- Every bus event goes to the UI. Mic and speech levels stream at 30 Hz so the core reacts to real audio.
- Each UI command is checked against an allow-list, and anything with a side effect is written to the audit trace.
"""
from __future__ import annotations

import asyncio
import json
import os
import platform
import secrets
import shutil
import string
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from aiohttp import WSMsgType, web

DIST = Path(__file__).resolve().parents[2] / "galaxy" / "dist"
EDITABLE_SETTINGS = {"user_name": str, "voice": str, "wake_sensitivity": float, "follow_up_seconds": float,
                     "proactive": bool, "briefing_time": str, "model_fast": str, "model_reasoning": str,
                     "approval_timeout": float, "home_assistant_url": str, "personality": str,
                     "graphics_quality": str}
VOICES = ["en-GB-RyanNeural", "en-GB-ThomasNeural", "en-US-GuyNeural", "en-US-AndrewNeural",
          "en-US-ChristopherNeural", "en-AU-WilliamNeural", "en-GB-SoniaNeural", "en-US-AriaNeural"]


def jsonable(v: Any) -> Any:
    try:
        json.dumps(v)
        return v
    except TypeError:
        return str(v)


class Bridge:
    def __init__(self, svc, app=None, audio=None, speaker=None, port: int = 8765):
        self.svc, self.app, self.audio, self.speaker, self.port = svc, app, audio, speaker, port
        self.token = secrets.token_urlsafe(18)
        self.clients: set[web.WebSocketResponse] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.state = "idle"
        self.started = time.time()
        svc.bus.subscribe("*", self._on_event)

    # ---------------- outbound ----------------
    def _on_event(self, ev) -> None:
        if ev.type == "voice.state":
            self.state = ev.data.get("state", self.state)
        if self.loop and self.clients:
            msg = {"type": "event", "event": ev.type, "data": {k: jsonable(v) for k, v in ev.data.items()},
                   "ts": ev.ts}
            self.loop.call_soon_threadsafe(asyncio.ensure_future, self._broadcast(msg))

    async def _broadcast(self, msg: dict) -> None:
        data = json.dumps(msg)
        for ws in list(self.clients):
            try:
                await ws.send_str(data)
            except Exception:
                self.clients.discard(ws)

    async def _levels(self) -> None:
        while True:
            await asyncio.sleep(1 / 30)
            if not self.clients:
                continue
            conv = getattr(self.app, "conv", None)
            if conv is not None:            # conversation mode owns the mic and the speaker
                mic, spk = conv.mic_level, conv.speech_level
            else:
                mic = float(getattr(self.audio, "level", 0.0) or 0.0) if self.audio else 0.0
                spk = float(self.speaker.level) if self.speaker else 0.0
            await self._broadcast({"type": "levels", "mic": round(mic, 3), "speech": round(spk, 3)})

    def snapshot(self) -> dict:
        s = self.svc
        return {"type": "snapshot", "settings": s.settings.public(), "voices": VOICES,
                "state": "privacy" if s.privacy else self.state, "privacy": s.privacy,
                "memory_enabled": not s.memory.paused, "has_mic": self.audio is not None,
                "tools": sorted(s.registry.tools), "user": os.getenv("USERNAME", "user"),
                "mock": {"email": type(s.email).__name__.startswith("Mock"),
                         "calendar": type(s.calendar).__name__.startswith("Mock")}}

    # ---------------- inbound ----------------
    def audit(self, name: str, detail: dict, status: str = "ok") -> None:
        self.svc.tracer.record(None, "ui", name, status=status, detail=detail)

    async def handle(self, msg: dict) -> dict | None:
        t, s = msg.get("type"), self.svc
        app = self.app
        if t == "text":
            text = str(msg.get("text", ""))[:4000]
            if app:
                app.submit_text(text)
            return None
        if t == "wake":
            app and app.trigger_wake()
            return None
        if t == "interrupt":
            if self.speaker:
                self.speaker.interrupt()
            if app:
                await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(app.agent.cancel(), app.loop)) \
                    if getattr(app, "loop", None) else None
            s.bus.publish("voice.state", state="idle")
            return None
        if t == "window.minimize":
            from .window import minimize_windows
            return {"ok": await asyncio.to_thread(minimize_windows) > 0}
        if t == "window.close":
            # shut JARVIS down; completely=False keeps the offline "Jarvis" listener (supervisor) running
            completely = bool(msg.get("completely"))
            self.audit("window.close", {"completely": completely})
            if app:
                app.request_quit(completely=completely)
            else:
                from .window import close_windows
                close_windows()
            return {"ok": True}
        if t == "conversation":
            if app and getattr(app, "voice", None) is None:
                return {"error": "Conversation mode needs a microphone."}
            if app and msg.get("on"):
                if not getattr(app, "conv", None):
                    app.submit_text("Let's talk.")
            elif app:
                app.stop_conversation()
            return {"ok": True}
        if t == "emergency_stop":
            if app and getattr(app, "conv", None):
                app.conv.stop("emergency")
            if self.speaker:
                self.speaker.interrupt()
            s.approvals.resolve_pending("denied", "emergency_stop")
            await self.on_app(lambda: app.agent.cancel())
            self.audit("emergency_stop", {})
            s.bus.publish("notify", text="Emergency stop: all actions halted.", source="ui")
            return None
        if t == "approval":
            ok = s.approvals.resolve_pending("approved" if msg.get("approve") else "denied", "ui")
            return {"ok": ok}
        if t == "privacy":
            if app:
                app.set_privacy(bool(msg.get("on")))
            return None
        if t == "clear_conversation":
            await self.on_app(lambda: app.agent.reset())
            self.audit("clear_conversation", {})
            return {"ok": True}
        if t == "open_url":
            url = str(msg.get("url", ""))
            u = urlparse(url)
            if u.scheme not in ("http", "https") or not u.netloc:
                return {"error": "Only http(s) links can be opened."}
            webbrowser.open(url)
            self.audit("open_url", {"url": url})
            return {"ok": True}
        if t == "run_tool":
            # The UI can call registered tools. They go through the same policy/approval/audit path as the agent.
            name, args = str(msg.get("tool")), msg.get("args") or {}
            if name not in s.registry.tools:
                return {"error": f"Unknown tool {name}"}
            res = await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(
                s.registry.execute(name, args), app.loop)) if app and getattr(app, "loop", None) \
                else await s.registry.execute(name, args)
            return {"text": res.text, "is_error": res.is_error}
        if t == "memory.list":
            q = str(msg.get("query") or "").strip()
            items = s.memory.search(q, limit=100) if q else s.memory.list(limit=200)
            return {"items": items, "enabled": not s.memory.paused}
        if t == "memory.update":
            ok = s.memory.update(int(msg["id"]), str(msg["content"]))
            self.audit("memory.update", {"id": msg["id"]})
            return {"ok": ok}
        if t == "memory.delete":
            ok = s.memory.forget(int(msg["id"]))
            self.audit("memory.delete", {"id": msg["id"]})
            return {"ok": ok}
        if t == "memory.add":
            mid, note = s.memory.add(str(msg["content"]), str(msg.get("category", "fact")), "user")
            return {"id": mid, "note": note}
        if t == "memory.enable":
            s.memory.paused = not bool(msg.get("on"))
            self.audit("memory.enable", {"on": bool(msg.get("on"))})
            return {"enabled": not s.memory.paused}
        if t == "history.clear":
            n = s.db.execute("DELETE FROM runs") if msg.get("confirm") else 0
            s.db.execute("DELETE FROM trace WHERE kind != 'ui'") if msg.get("confirm") else None
            self.audit("history.clear", {})
            return {"ok": bool(msg.get("confirm")), "deleted": n}
        if t == "history.list":
            rows = s.db.query("SELECT id, started_at, channel, input, output, status FROM runs "
                              "ORDER BY id DESC LIMIT 60")
            return {"items": [dict(r) for r in rows]}
        if t == "settings.update":
            changed = {}
            for k, v in (msg.get("values") or {}).items():
                if k in EDITABLE_SETTINGS:
                    setattr(s.settings, k, EDITABLE_SETTINGS[k](v))
                    changed[k] = getattr(s.settings, k)
            if "voice" in changed and self.speaker:
                self.speaker.voice = changed["voice"]
            s.settings.save()
            self.audit("settings.update", changed)
            s.bus.publish("settings.changed", **changed)
            return {"settings": s.settings.public()}
        if t == "tasks.list":
            return {"items": s.tasks.open_tasks(100)}
        if t == "tasks.create":
            from ..tasks.store import parse_when
            tid = s.tasks.create(str(msg["title"]), due_at=parse_when(msg.get("due")),
                                 kind="reminder" if msg.get("due") else "task")
            return {"id": tid}
        if t == "tasks.complete":
            return {"ok": s.tasks.complete(int(msg["id"]))}
        if t == "notes.list":
            q = str(msg.get("query") or "").strip()
            return {"items": s.notes.search(q, 50) if q else s.notes.recent(50)}
        if t == "notes.create":
            nid = s.notes.create(str(msg.get("title") or "Note"), str(msg.get("body") or ""))
            return {"id": nid}
        if t == "notes.delete":
            s.notes.delete(int(msg["id"]))
            return {"ok": True}
        if t == "files.list":
            return self.list_dir(str(msg.get("path") or ""))
        if t == "files.open":
            p = self.guard(str(msg.get("path")))
            if not p:
                return {"error": "Outside allowed folders."}
            if p.suffix.lower() in {".exe", ".bat", ".cmd", ".ps1", ".vbs", ".msi", ".scr", ".js", ".lnk"}:
                return {"error": "Executables are not opened from the file browser. Ask JARVIS (needs approval)."}
            os.startfile(str(p))  # noqa: S606 (allow-listed folders, non-executable types)
            self.audit("files.open", {"path": str(p)})
            return {"ok": True}
        if t == "sysinfo":
            return self.sysinfo()
        if t == "audit.list":
            return {"items": s.tracer.recent_activity(int(msg.get("limit", 80))), "metrics": s.tracer.metrics()}
        if t == "permissions.update":
            # Trust level and tool lists are security settings: they change only here, in the UI, never by voice.
            lvl = int(msg.get("trust_level", s.settings.trust_level))
            if not 0 <= lvl <= 4:
                return {"error": "Trust level must be 0-4."}
            s.settings.trust_level = lvl
            for key in ("trusted_tools", "always_ask_tools"):
                if key in msg:
                    s.settings.__setattr__(key, [x for x in msg[key] if x in s.registry.tools])
            s.settings.save()
            self.audit("permissions.update", {"trust_level": lvl})
            return {"settings": s.settings.public()}
        if t == "secrets.status":
            from ..core import secrets
            return {"status": secrets.status(), "labels": secrets.KNOWN}
        if t == "secrets.set":
            from ..core import secrets
            name = str(msg.get("name"))
            if name not in secrets.KNOWN:
                return {"error": "Unknown key name."}
            await asyncio.to_thread(secrets.set_secret, name, str(msg.get("value") or "") or None)
            self.audit("secrets.set", {"name": name, "cleared": not msg.get("value")})   # never the value
            return {"status": secrets.status()}
        if t in ("ha.states", "ha.call", "ha.ping"):
            from ..connectors.home_assistant import CONTROLLABLE, SENSITIVE, HomeAssistant
            ha = HomeAssistant(s.settings.home_assistant_url)
            try:
                if t == "ha.ping":
                    return {"message": await asyncio.to_thread(ha.ping)}
                if t == "ha.states":
                    return {"items": await asyncio.to_thread(ha.states)}
                ent = str(msg["entity_id"])
                domain, service = ent.split(".")[0], str(msg["service"])
                if domain not in CONTROLLABLE | SENSITIVE:
                    return {"error": f"{domain} entities can't be controlled here."}
                if domain in SENSITIVE and not msg.get("confirmed"):
                    return {"error": "Locks and alarms need explicit confirmation.", "needs_confirm": True}
                await asyncio.to_thread(ha.call, domain, service, ent, msg.get("data"))
                self.audit("ha.call", {"entity": ent, "service": service})
                return {"ok": True}
            except Exception as e:
                return {"error": str(e)}
        if t == "snapshot":
            return self.snapshot()
        return {"error": f"unknown command {t}"}

    async def on_app(self, make_coro):
        """Run a coroutine on the JARVIS main loop (the agent lives there) and wait for its result."""
        loop = getattr(self.app, "loop", None)
        if self.app is None or loop is None:
            return None
        return await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(make_coro(), loop))

    def guard(self, raw: str) -> Path | None:
        try:
            p = Path(raw).expanduser().resolve()
        except (OSError, ValueError):
            return None
        for root in self.svc.settings.file_roots:
            r = Path(root).resolve()
            if p == r or r in p.parents:
                return p
        return None

    def list_dir(self, raw: str) -> dict:
        roots = [{"name": Path(r).name, "path": str(Path(r)), "dir": True} for r in self.svc.settings.file_roots]
        if not raw:
            return {"path": "", "items": roots, "roots": roots}
        p = self.guard(raw)
        if not p or not p.is_dir():
            return {"error": "Outside allowed folders.", "roots": roots}
        items = []
        try:
            for e in sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))[:500]:
                try:
                    st = e.stat()
                    items.append({"name": e.name, "path": str(e), "dir": e.is_dir(), "size": st.st_size,
                                  "mtime": st.st_mtime})
                except OSError:
                    continue
        except PermissionError:
            return {"error": "Permission denied.", "roots": roots}
        parent = str(p.parent) if self.guard(str(p.parent)) else ""
        return {"path": str(p), "parent": parent, "items": items, "roots": roots}

    def sysinfo(self) -> dict:
        disks = []
        for letter in string.ascii_uppercase:
            d = f"{letter}:\\"
            if os.path.exists(d):
                try:
                    u = shutil.disk_usage(d)
                    disks.append({"drive": d, "total": u.total, "free": u.free})
                except OSError:
                    pass
        info = {"os": f"{platform.system()} {platform.release()} ({platform.version()})",
                "machine": platform.machine(), "cpu": platform.processor(), "cores": os.cpu_count(),
                "python": platform.python_version(), "hostname": platform.node(), "disks": disks,
                "uptime_s": round(time.time() - self.started), "metrics": self.svc.tracer.metrics()}
        try:
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                            ("avail", ctypes.c_ulonglong), ("a", ctypes.c_ulonglong), ("b", ctypes.c_ulonglong),
                            ("c", ctypes.c_ulonglong), ("d", ctypes.c_ulonglong), ("e", ctypes.c_ulonglong)]
            m = MS()
            m.l = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            info["memory"] = {"total": m.total, "free": m.avail, "load": m.load}
        except Exception:
            pass
        return info

    # ---------------- server ----------------
    async def ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        if request.query.get("token") != self.token:
            raise web.HTTPForbidden(text="bad token")
        origin = request.headers.get("Origin", "")
        if origin and urlparse(origin).hostname not in ("127.0.0.1", "localhost"):
            raise web.HTTPForbidden(text="bad origin")      # blocks other websites from driving JARVIS
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=1 << 20)
        await ws.prepare(request)
        self.clients.add(ws)
        await ws.send_str(json.dumps(self.snapshot()))
        try:
            async for m in ws:
                if m.type != WSMsgType.TEXT:
                    continue
                try:
                    msg = json.loads(m.data)
                    res = await self.handle(msg)
                except Exception as e:  # report, never swallow
                    print(f"[bridge] command error: {e!r}")
                    res = {"error": str(e)}
                if res is not None and msg.get("rid") is not None:
                    await ws.send_str(json.dumps({"type": "reply", "rid": msg["rid"], **res}, default=str))
        finally:
            self.clients.discard(ws)
        return ws

    def make_app(self) -> web.Application:
        wa = web.Application()
        wa.router.add_get("/ws", self.ws_handler)

        async def index(_):
            if not (DIST / "index.html").exists():
                return web.Response(text="Galaxy UI not built. Run: cd galaxy && npm install && npm run build",
                                    status=500)
            return web.FileResponse(DIST / "index.html", headers={"Cache-Control": "no-cache"})
        wa.router.add_get("/", index)
        if (DIST / "assets").exists():
            wa.router.add_static("/assets", DIST / "assets")
        return wa

    async def serve(self) -> None:
        self.loop = asyncio.get_running_loop()
        runner = web.AppRunner(self.make_app())
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", self.port).start()
        print(f"[bridge] galaxy UI on {self.url}")
        await self._levels()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/?token={self.token}"

    def start_thread(self) -> threading.Thread:
        th = threading.Thread(target=lambda: asyncio.run(self.serve()), daemon=True, name="galaxy-bridge")
        th.start()
        return th


def open_window(url: str) -> None:
    """Open the UI as a chromeless full-screen app window (Edge or Chrome), else the default browser."""
    import subprocess
    cands = [Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft/Edge/Application/msedge.exe",
             Path(os.environ.get("ProgramFiles", "")) / "Microsoft/Edge/Application/msedge.exe",
             Path(os.environ.get("ProgramFiles", "")) / "Google/Chrome/Application/chrome.exe",
             Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe"]
    profile = Path(__file__).resolve().parents[2] / "data" / "galaxy-profile"
    for exe in cands:
        if exe.exists():
            subprocess.Popen([str(exe), f"--app={url}", "--start-fullscreen", f"--user-data-dir={profile}",
                              "--autoplay-policy=no-user-gesture-required", "--no-first-run"])
            return
    webbrowser.open(url)
