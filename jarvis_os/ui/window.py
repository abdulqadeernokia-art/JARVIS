"""JARVIS window: animated presence orb, live activity panel, approval card, compact floating mode.

Driven entirely by EventBus events (queued into the Tk thread), not by polling component state.
"""
from __future__ import annotations

import datetime as dt
import math
import queue
import random
import time
import tkinter as tk
from typing import Callable

BG, PANEL, TEXT, DIM = "#05080d", "#0b131c", "#cfe8f5", "#5d7a8c"
STATES = {   # main colour, glow colour, label
    "idle": ("#1f6f8b", "#0b2a36", "STANDBY"),
    "listening": ("#00e5ff", "#004b5c", "LISTENING"),
    "transcribing": ("#00e5ff", "#004b5c", "UNDERSTANDING"),
    "thinking": ("#ffb300", "#4d3500", "THINKING"),
    "working": ("#ff8f00", "#4d2a00", "WORKING"),
    "speaking": ("#4fc3ff", "#0d3a55", "SPEAKING"),
    "approval": ("#e040fb", "#3d0f47", "AWAITING APPROVAL"),
    "error": ("#ff5252", "#4d1010", "ERROR"),
    "privacy": ("#7c4dff", "#1f1147", "PRIVACY MODE"),
    "dictating": ("#00e676", "#00401f", "DICTATING"),
    "meeting": ("#00e676", "#00401f", "MEETING MODE"),
}


def mix(c1: str, c2: str, t: float) -> str:
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(x + (y - x) * max(0, min(1, t))) for x, y in zip(a, b))


class JarvisWindow:
    FULL = (940, 600)
    COMPACT = (300, 330)

    def __init__(self, bus, level_fn: Callable[[], float], on_wake: Callable[[], None],
                 on_approval: Callable[[str], None], on_quit: Callable[[], None], hotkey: str,
                 on_quit_completely: Callable[[], None] | None = None):
        self.level_fn, self.on_wake, self.on_approval, self.on_quit = level_fn, on_wake, on_approval, on_quit
        self.events: queue.Queue = queue.Queue()
        bus.subscribe("*", self.events.put)
        self.state, self.base_state = "idle", "idle"
        self.caption, self.heard = "", ""
        self.level, self.bars, self.sparks = 0.0, [0.0] * 72, []
        self.compact = False
        self.t0 = time.time()
        self.error_until = 0.0
        self.hotkey = hotkey

        self.root = tk.Tk()
        self.root.title("J.A.R.V.I.S.")
        self.root.configure(bg=BG)
        self.root.geometry("%dx%d" % self.FULL)
        self.root.minsize(*self.COMPACT)
        self.root.protocol("WM_DELETE_WINDOW", self.root.iconify)   # closing = minimise; quit by voice/menu

        self.canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0, width=520)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Button-1>", lambda e: self.on_wake())
        self.root.bind("<space>", lambda e: self.on_wake())
        self.root.bind("<F11>", lambda e: self.toggle_compact())
        self.canvas.bind("<Double-Button-1>", lambda e: self.toggle_compact())

        self.panel = tk.Frame(self.root, bg=PANEL, width=420)
        self.panel.pack(side="right", fill="y")
        self.panel.pack_propagate(False)
        tk.Label(self.panel, text="ACTIVITY", bg=PANEL, fg=DIM, font=("Consolas", 10, "bold"),
                 anchor="w").pack(fill="x", padx=14, pady=(14, 4))
        self.activity = tk.Text(self.panel, bg=PANEL, fg=TEXT, bd=0, wrap="word", font=("Consolas", 9),
                                height=20, state="disabled", cursor="arrow")
        self.activity.pack(fill="both", expand=True, padx=14)
        for tag, col in (("time", DIM), ("tool", "#ffb300"), ("ok", "#69f0ae"), ("err", "#ff5252"),
                         ("you", "#00e5ff"), ("jarvis", TEXT), ("appr", "#e040fb"), ("note", "#82b1ff")):
            self.activity.tag_config(tag, foreground=col)

        self.approval = tk.Frame(self.panel, bg="#1a0f22", highlightbackground="#e040fb", highlightthickness=1)
        self.appr_title = tk.Label(self.approval, text="", bg="#1a0f22", fg="#f3c6ff", wraplength=380,
                                   justify="left", font=("Segoe UI", 10, "bold"))
        self.appr_title.pack(fill="x", padx=10, pady=(8, 2))
        self.appr_body = tk.Label(self.approval, text="", bg="#1a0f22", fg=TEXT, wraplength=380, justify="left",
                                  font=("Consolas", 9))
        self.appr_body.pack(fill="x", padx=10)
        btns = tk.Frame(self.approval, bg="#1a0f22")
        btns.pack(fill="x", padx=10, pady=8)
        tk.Button(btns, text="Approve", command=lambda: self.on_approval("approved"), bg="#2e7d32", fg="white",
                  bd=0, padx=14, pady=4).pack(side="left")
        tk.Button(btns, text="Cancel", command=lambda: self.on_approval("denied"), bg="#5d1f1f", fg="white",
                  bd=0, padx=14, pady=4).pack(side="left", padx=8)

        hint = f"Say \"Jarvis\" (also to interrupt)  ·  {hotkey.upper()} or click the orb  ·  double-click = compact"
        tk.Label(self.panel, text=hint, bg=PANEL, fg=DIM, font=("Segoe UI", 8)).pack(fill="x", pady=(4, 10))

        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Compact / floating mode", command=self.toggle_compact)
        menu.add_command(label="Minimise", command=self.root.iconify)
        menu.add_separator()
        menu.add_command(label="Shut down (say \"Jarvis\" to wake me)", command=self.on_quit)
        if on_quit_completely:
            menu.add_command(label="Quit completely (stop listening)", command=on_quit_completely)
        self.canvas.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))

        self.log("JARVIS", "starting up...", "note")
        self._tick()

    # ---------------- events ----------------
    def _handle(self, ev) -> None:
        d, t = ev.data, ev.type
        if t == "voice.state":
            s = d["state"]
            if s in STATES:
                self.base_state = s
        elif t == "voice.transcript" and not d.get("partial"):
            self.heard = d["text"]
            self.log("You", d["text"], "you")
        elif t == "agent.thinking":
            self.base_state = "thinking"
            self.log("route", f"{d['route']} -> {d['model']}", "time")
        elif t == "agent.text":
            self.caption = d["text"]
        elif t == "speaker":
            self.base_state = "speaking" if d["speaking"] else ("idle" if self.base_state == "speaking"
                                                                 else self.base_state)
            if d.get("text"):
                self.caption = d["text"]
                self.log("JARVIS", d["text"], "jarvis")
        elif t == "tool.started":
            self.base_state = "working"
            self.log("tool", f"{d['tool']}  {d.get('summary', '')[:90]}", "tool")
        elif t == "tool.finished":
            self.base_state = "thinking"
            tag = "ok" if d["status"] == "ok" else "err"
            self.log("  ->", f"{d['status']} ({d['ms']} ms)", tag)
        elif t == "approval.requested":
            self.appr_title.config(text=f"JARVIS wants to: {d['summary']}")
            self.appr_body.config(text=d["preview"][:600])
            self.approval.pack(fill="x", padx=14, pady=6, before=self.activity)
            self.base_state = "approval"
            self.log("approval", d["summary"], "appr")
        elif t == "approval.resolved":
            self.approval.pack_forget()
            self.base_state = "thinking"
            self.log("approval", f"{d['decision']} (by {d['by']})", "appr")
        elif t in ("agent.completed", "agent.cancelled"):
            if self.base_state not in ("speaking", "privacy", "meeting"):
                self.base_state = "idle"
        elif t == "agent.failed":
            self.error_until = time.time() + 3
            self.log("error", d.get("output", "failed")[:120], "err")
        elif t == "notify":
            self.log("notice", d.get("text") or "", "note")
        elif t == "privacy.changed":
            self.base_state = "privacy" if d["on"] else "idle"
            self.log("privacy", "ON - not listening, not remembering" if d["on"] else "off", "appr")
        elif t == "meeting.started":
            self.log("meeting", f"started: {d['title']}", "note")
        elif t == "meeting.segment":
            self.log(d["clock"], d["text"], "you")
        elif t == "app.quit":
            self.root.destroy()

    def log(self, who: str, text: str, tag: str) -> None:
        self.activity.config(state="normal")
        self.activity.insert("end", dt.datetime.now().strftime("%H:%M:%S "), "time")
        self.activity.insert("end", f"{who}: ", tag)
        self.activity.insert("end", text + "\n", "jarvis")
        lines = int(self.activity.index("end-1c").split(".")[0])
        if lines > 400:
            self.activity.delete("1.0", f"{lines - 400}.0")
        self.activity.see("end")
        self.activity.config(state="disabled")

    def toggle_compact(self) -> None:
        self.compact = not self.compact
        if self.compact:
            self.panel.pack_forget()
            self.root.geometry("%dx%d" % self.COMPACT)
            self.root.attributes("-topmost", True)
        else:
            self.panel.pack(side="right", fill="y")
            self.root.geometry("%dx%d" % self.FULL)
            self.root.attributes("-topmost", False)

    # ---------------- animation ----------------
    def _tick(self) -> None:
        try:
            while True:
                self._handle(self.events.get_nowait())
        except queue.Empty:
            pass
        except tk.TclError:
            return
        self.state = "error" if time.time() < self.error_until else self.base_state
        try:
            self._draw(time.time() - self.t0)
        except tk.TclError:
            return
        self.root.after(33, self._tick)

    def _draw(self, t: float) -> None:
        c = self.canvas
        c.delete("all")
        W, H = max(c.winfo_width(), 200), max(c.winfo_height(), 200)
        cx, cy = W / 2, H * (0.45 if not self.compact else 0.42)
        R = min(W, H) * (0.30 if not self.compact else 0.30)
        main, glow, label = STATES.get(self.state, STATES["idle"])
        mic = self.level_fn()
        target = {"idle": 0.15 + 0.05 * math.sin(t * 1.5), "listening": 0.3 + min(0.7, mic * 2.5),
                  "transcribing": 0.45, "thinking": 0.5 + 0.1 * math.sin(t * 6), "working": 0.6,
                  "speaking": 0.4 + random.random() * 0.6, "approval": 0.45 + 0.25 * math.sin(t * 5),
                  "error": 0.7, "privacy": 0.1, "dictating": 0.3 + min(0.7, mic * 2.5),
                  "meeting": 0.3 + min(0.7, mic * 2.5)}.get(self.state, 0.2)
        self.level += (target - self.level) * 0.25

        for x in range(0, int(W), 40):
            c.create_line(x, 0, x, H, fill="#0a121b")
        for y in range(0, int(H), 40):
            c.create_line(0, y, W, y, fill="#0a121b")

        for i in range(10, 0, -1):
            r = R * 0.5 + self.level * R * 0.25 + i * R * 0.06
            c.create_oval(cx - r, cy - r, cx + r, cy + r, outline="", fill=mix(BG, glow, (11 - i) / 14))

        n = len(self.bars)
        for i in range(n):
            if self.state == "speaking":
                tgt = random.random() * self.level
            elif self.state in ("listening", "dictating", "meeting"):
                tgt = 0.08 + min(0.9, mic * 3) * (0.5 + 0.5 * random.random())
            elif self.state in ("thinking", "working"):
                tgt = 0.15 + 0.15 * math.sin(t * 8 + i * 0.5)
            else:
                tgt = 0.04
            self.bars[i] += (tgt - self.bars[i]) * 0.35
            a = i / n * 2 * math.pi
            r1, r2 = R, R + R * 0.06 + self.bars[i] * R * 0.4
            c.create_line(cx + r1 * math.cos(a), cy + r1 * math.sin(a), cx + r2 * math.cos(a), cy + r2 * math.sin(a),
                          fill=main, width=2 if self.compact else 3)

        speed = {"idle": 20, "listening": 60, "thinking": 200, "working": 260, "speaking": 90,
                 "approval": 40, "privacy": 5}.get(self.state, 40)
        for k, (rr, segs, w, dirn) in enumerate([(0.9, 6, 3, 1), (0.78, 3, 6, -1), (0.66, 12, 2, 1)]):
            r = R * rr
            off = (t * speed * dirn * (1 + k * 0.3)) % 360
            for s in range(segs):
                c.create_arc(cx - r, cy - r, cx + r, cy + r, start=off + s * 360 / segs, extent=360 / segs * 0.6,
                             style="arc", outline=main, width=w)

        core = R * 0.3 + self.level * R * 0.15
        c.create_oval(cx - core, cy - core, cx + core, cy + core, fill=mix(glow, main, 0.5), outline=main, width=3)
        inner = core * 0.55
        c.create_oval(cx - inner, cy - inner, cx + inner, cy + inner,
                      fill=mix(main, "#ffffff", 0.5 + self.level * 0.4), outline="")

        if self.state in ("speaking", "thinking", "working") and random.random() < 0.6:
            self.sparks.append([random.random() * 2 * math.pi, R * 1.05, 1.0])
        for p in self.sparks:
            p[1] += R * 0.025
            p[2] -= 0.04
        self.sparks = [p for p in self.sparks if p[2] > 0]
        for a, r, life in self.sparks:
            x, y = cx + r * math.cos(a), cy + r * math.sin(a)
            c.create_oval(x - 2, y - 2, x + 2, y + 2, fill=mix(BG, main, life), outline="")

        c.create_text(cx, 26 if self.compact else 36, text="J . A . R . V . I . S", fill=main,
                      font=("Consolas", 13 if self.compact else 20, "bold"))
        c.create_text(cx, cy + R * 1.42, text=label, fill=main, font=("Consolas", 9 if self.compact else 11))
        cap = self.caption if len(self.caption) < 200 else self.caption[:197] + "..."
        c.create_text(cx, cy + R * 1.42 + (26 if self.compact else 40), text=cap, fill=TEXT, width=W - 40,
                      font=("Segoe UI", 9 if self.compact else 11), justify="center")

    def run(self) -> None:
        self.root.mainloop()
