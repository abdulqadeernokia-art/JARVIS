"""Computer control: see the screen, operate mouse/keyboard/windows, launch apps, media and system controls.

The agent is instructed to follow OBSERVE -> ACT -> VERIFY: take a screenshot (or list windows) before acting
on the UI and again afterwards to confirm the result.
"""
from __future__ import annotations

import asyncio
import ctypes
import re
import sys
import urllib.parse
import urllib.request
import webbrowser

from ..computer.controller import is_terminal
from ..safety.policy import Risk
from .registry import S, Tool, ToolResult

_VK = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1, "stop": 0xB2,
       "volume_up": 0xAF, "volume_down": 0xAE, "mute": 0xAD}


SHELL_LAUNCH = re.compile(r"(powershell|pwsh|cmd(\.exe)?\b|wsl|bash|wscript|cscript|mshta|rundll32|regsvr32|"
                          r"[|&;<>^`]|\s-c(ommand)?\b|\s/c\b|\.(ps1|bat|cmd|vbs|js|exe|msi)\b|https?://)", re.I)


def register(svc) -> None:
    reg, pc = svc.registry, svc.computer

    def keyboard_risk(a) -> Risk:
        """Typing into a terminal is running code: always ask first."""
        return Risk.DANGEROUS if is_terminal(pc.active_window_title()) else Risk.LOCAL

    def launch_risk(a) -> Risk:
        """Plain app names are fine; anything that looks like a command line or script needs approval."""
        return Risk.DANGEROUS if SHELL_LAUNCH.search(a.get("name", "")) else Risk.LOCAL

    def terminal_note(a) -> str:
        t = pc.active_window_title()
        return f" into TERMINAL window '{t}' (this runs commands)" if is_terminal(t) else ""

    def th(fn):
        async def run(a):
            return await asyncio.to_thread(fn, a)
        return run

    def shot(a):
        mon = int(a.get("monitor") or 0)
        s = pc.screenshot(mon)
        mons = pc.monitors()
        layout = "; ".join(f"monitor {i + 1}: x {m[0]}..{m[2]}, y {m[1]}..{m[3]}" for i, m in enumerate(mons))
        return ToolResult(f"Screenshot of {'all monitors' if not mon else f'monitor {mon}'}, {s.width}x{s.height}. "
                          f"Active window: '{pc.active_window_title()}'. "
                          f"Desktop layout (real pixels): {layout}. Give click coordinates in THIS screenshot's "
                          "pixels; they will be mapped for you (each new screenshot resets the mapping). Only act on "
                          "elements you can actually see; if unsure, say so.",
                          image_png_b64=s.png_b64, image_mime=s.mime, sources=["screen"])
    reg.register(Tool("screenshot", "See the screen. monitor=0 (default) shows all monitors side by side; 1, 2... "
                      "shows one monitor in more detail (better for reading text). Use before acting on any UI and "
                      "afterwards to verify. Also for 'what's on my screen', reading errors, OCR.",
                      {"monitor": S("integer", "0 = all, 1 = primary, 2 = second...")}, th(shot), required=[],
                      timeout=20, category="computer"))

    def windows(a):
        ws = pc.windows()
        return "\n".join(f"{'* ' if w.get('active') else '  '}{w['title']}{' (minimized)' if w.get('minimized') else ''}"
                         f"{' at x=%d,y=%d' % (w['x'], w['y']) if 'x' in w else ''}" for w in ws) or "No windows."
    reg.register(Tool("list_windows", "List open windows (* = active). Cheap way to verify an app opened.", {},
                      th(windows), category="computer"))

    def click(a):
        pc.click(int(a["x"]), int(a["y"]), a.get("button") or "left", int(a.get("clicks") or 1))
        return f"Clicked at ({a['x']},{a['y']}). Verify with a screenshot if the outcome matters."
    reg.register(Tool("click", "Click at screenshot coordinates. clicks=2 for double-click; button right for "
                      "context menus.",
                      {"x": S("integer", ""), "y": S("integer", ""), "button": S("string", "left|right|middle"),
                       "clicks": S("integer", "1 or 2")}, th(click), Risk.LOCAL, required=["x", "y"],
                      summarize=lambda a: f"click at {a['x']},{a['y']}", category="computer"))

    def move(a):
        pc.move(int(a["x"]), int(a["y"]))
        return "Moved."
    reg.register(Tool("move_mouse", "Move the mouse (e.g. to hover).", {"x": S("integer", ""), "y": S("integer", "")},
                      th(move), Risk.LOCAL, category="computer"))

    def drag(a):
        pc.drag(int(a["x1"]), int(a["y1"]), int(a["x2"]), int(a["y2"]))
        return "Dragged."
    reg.register(Tool("drag", "Drag from one point to another.",
                      {k: S("integer", "") for k in ("x1", "y1", "x2", "y2")}, th(drag), Risk.LOCAL,
                      category="computer"))

    def type_(a):
        pc.type_text(a["text"])
        if str(a.get("press_enter", False)).lower() in ("true", "1"):
            pc.hotkey(["enter"])
        return "Typed."
    reg.register(Tool("type_text", "Type text into the focused field/window.",
                      {"text": S("string", ""), "press_enter": S("boolean", "Press Enter afterwards.")},
                      th(type_), Risk.LOCAL, required=["text"], risk_fn=keyboard_risk,
                      summarize=lambda a: f"type '{a['text'][:80]}'{terminal_note(a)}", category="computer"))

    def keys(a):
        ks = [k.strip() for k in re.split(r"[+,\s]+", a["keys"]) if k.strip()]
        pc.hotkey(ks)
        return f"Pressed {'+'.join(ks)}."
    reg.register(Tool("press_keys", "Press a key or shortcut, e.g. 'enter', 'ctrl+s', 'alt+tab', 'win+d'.",
                      {"keys": S("string", "")}, th(keys), Risk.LOCAL, risk_fn=keyboard_risk,
                      summarize=lambda a: f"press {a['keys']}{terminal_note(a)}", category="computer"))

    def scroll(a):
        pc.scroll(int(a["amount"]), a.get("x"), a.get("y"))
        return "Scrolled."
    reg.register(Tool("scroll", "Scroll (positive = up, negative = down), optionally over a point.",
                      {"amount": S("integer", "Notches"), "x": S("integer", ""), "y": S("integer", "")},
                      th(scroll), Risk.LOCAL, required=["amount"], category="computer"))

    def focus(a):
        t = pc.focus_window(a["title_contains"])
        return f"Focused '{t}'." if t else "No window with that title."
    reg.register(Tool("focus_window", "Bring a window to the front by part of its title.",
                      {"title_contains": S("string", "")}, th(focus), Risk.LOCAL, category="computer"))

    def winact(a):
        t = pc.window_action(a["title_contains"], a["action"])
        return f"{a['action']} '{t}'." if t else "No window with that title."
    reg.register(Tool("window_action", "minimize | maximize | restore | close a window. Closing may lose unsaved "
                      "work, so check first.",
                      {"title_contains": S("string", ""), "action": S("string", "", enum=["minimize", "maximize",
                                                                                          "restore", "close"])},
                      th(winact), Risk.LOCAL, summarize=lambda a: f"{a['action']} window '{a['title_contains']}'",
                      category="computer"))

    def clip_get(a):
        return ToolResult(f"Clipboard:\n{pc.get_clipboard()[:5000]}", sources=["clipboard"])
    reg.register(Tool("read_clipboard", "Read the clipboard text.", {}, th(clip_get), category="computer"))

    def clip_set(a):
        pc.set_clipboard(a["text"])
        return "Copied to clipboard."
    reg.register(Tool("copy_to_clipboard", "Put text on the clipboard.", {"text": S("string", "")},
                      th(clip_set), Risk.LOCAL, category="computer"))

    def launch(a):
        pc.launch(a["name"])
        return f"Launching {a['name']}. Verify with list_windows after a moment if needed."
    reg.register(Tool("open_application", "Launch an app by name or executable (notepad, calc, chrome, spotify, "
                      "explorer, winword...). Plain app names only; command lines and scripts need approval.",
                      {"name": S("string", "")}, th(launch), Risk.LOCAL, risk_fn=launch_risk,
                      summarize=lambda a: f"open {a['name']}", category="computer"))

    def url(a):
        webbrowser.open(a["url"])
        return f"Opened {a['url']} in the default browser."
    reg.register(Tool("open_url", "Open a URL in the default browser.", {"url": S("string", "Full URL")},
                      th(url), Risk.LOCAL, category="browser"))

    def youtube(a):
        q = urllib.parse.quote_plus(a["query"])
        target = f"https://www.youtube.com/results?search_query={q}"
        try:
            req = urllib.request.Request(target, headers={"User-Agent": "Mozilla/5.0"})
            html = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", "ignore")
            m = re.search(r'"videoId":"([\w-]{11})"', html)
            if m:
                target = f"https://www.youtube.com/watch?v={m.group(1)}"
        except Exception:
            pass
        webbrowser.open(target)
        return ToolResult(f"Playing YouTube result for '{a['query']}'.", sources=[target])
    reg.register(Tool("play_on_youtube", "Find and play a video/song on YouTube.", {"query": S("string", "")},
                      th(youtube), Risk.LOCAL, category="media"))

    def media(a):
        action = a["action"]
        if action not in _VK:
            return ToolResult(f"Unknown action {action}.", is_error=True)
        if sys.platform != "win32":
            return ToolResult("Media keys are only implemented on Windows.", is_error=True)
        steps = max(1, min(int(a.get("steps") or (5 if "volume" in action else 1)), 50))
        for _ in range(steps):
            ctypes.windll.user32.keybd_event(_VK[action], 0, 0, 0)
            ctypes.windll.user32.keybd_event(_VK[action], 0, 2, 0)
        return f"Done: {action} x{steps}."
    reg.register(Tool("media_control", "Media and volume: play_pause, next, previous, stop, volume_up, volume_down, "
                      "mute. Each volume step is ~2%.",
                      {"action": S("string", "", enum=list(_VK)), "steps": S("integer", "Repeat count")},
                      th(media), Risk.LOCAL, required=["action"], category="media"))

    def battery(a):
        class PS(ctypes.Structure):
            _fields_ = [("ac", ctypes.c_byte), ("flag", ctypes.c_byte), ("pct", ctypes.c_byte),
                        ("sys", ctypes.c_byte), ("life", ctypes.c_ulong), ("full", ctypes.c_ulong)]
        s = PS()
        ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s))
        pct = s.pct & 0xFF
        if pct == 255:
            return "No battery (mains powered)."
        return f"Battery {pct}%, {'charging' if s.ac == 1 else 'on battery'}."
    reg.register(Tool("system_status", "Battery level and charging state.", {}, th(battery), category="system"))

    def lock(a):
        ctypes.windll.user32.LockWorkStation()
        return "Locked."
    reg.register(Tool("lock_computer", "Lock the Windows session.", {}, th(lock), Risk.LOCAL, category="system"))
