"""Computer-control abstraction. Platform adapters implement ComputerController.

Coordinates exchanged with the model are in *screenshot pixels*; the controller converts them to real
screen pixels using the scale of the most recent screenshot, so the model never needs to know the DPI.
"""
from __future__ import annotations

import base64
import ctypes
import io
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

MAX_SHOT_WIDTH = 1600   # all monitors side by side are downscaled to this width


@dataclass
class Screenshot:
    png_b64: str      # base64 image data (JPEG unless mime says otherwise)
    width: int
    height: int
    scale: float      # real pixels per screenshot pixel
    mime: str = "image/jpeg"


TERMINAL_TITLES = ("powershell", "command prompt", "cmd.exe", "windows terminal", "terminal", "bash", "wsl",
                   "ubuntu", "git bash", "administrator:", "pwsh", "conhost")


def is_terminal(title: str) -> bool:
    t = (title or "").lower()
    return any(k in t for k in TERMINAL_TITLES)


class ComputerController(ABC):
    @abstractmethod
    def screenshot(self, monitor: int = 0) -> Screenshot:
        """monitor 0 = all monitors in one image; 1..n = a single monitor at higher detail."""

    def monitors(self) -> list[tuple[int, int, int, int]]:
        return [(0, 0, 1280, 720)]

    def active_window_title(self) -> str:
        return ""
    @abstractmethod
    def click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> None: ...
    @abstractmethod
    def move(self, x: int, y: int) -> None: ...
    @abstractmethod
    def drag(self, x1: int, y1: int, x2: int, y2: int) -> None: ...
    @abstractmethod
    def type_text(self, text: str) -> None: ...
    @abstractmethod
    def hotkey(self, keys: list[str]) -> None: ...
    @abstractmethod
    def scroll(self, amount: int, x: int | None = None, y: int | None = None) -> None: ...
    @abstractmethod
    def windows(self) -> list[dict]: ...
    @abstractmethod
    def focus_window(self, title_contains: str) -> str | None: ...
    @abstractmethod
    def window_action(self, title_contains: str, action: str) -> str | None: ...
    @abstractmethod
    def get_clipboard(self) -> str: ...
    @abstractmethod
    def set_clipboard(self, text: str) -> None: ...
    @abstractmethod
    def launch(self, target: str) -> None: ...


class WindowsController(ComputerController):
    def __init__(self):
        try:  # real pixel coordinates on high-DPI screens
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass
        import pyautogui
        pyautogui.FAILSAFE = True    # slam the mouse into a screen corner to abort automation
        pyautogui.PAUSE = 0.05
        self.pg = pyautogui
        self.user32 = ctypes.windll.user32
        self.scale = 1.0
        self.origin = (0, 0)   # top-left of the virtual desktop (negative if a monitor is left of/above primary)

    def _real(self, x: int, y: int) -> tuple[int, int]:
        return int(x * self.scale) + self.origin[0], int(y * self.scale) + self.origin[1]

    def monitors(self) -> list[tuple[int, int, int, int]]:
        """(left, top, right, bottom) of each monitor, primary first."""
        import ctypes.wintypes as wt
        rects = []
        proc = ctypes.WINFUNCTYPE(ctypes.c_int, wt.HMONITOR, wt.HDC, ctypes.POINTER(wt.RECT), wt.LPARAM)

        def cb(h, dc, r, lp):
            rects.append((r.contents.left, r.contents.top, r.contents.right, r.contents.bottom))
            return 1
        self.user32.EnumDisplayMonitors(None, None, proc(cb), 0)
        rects.sort(key=lambda r: (r[0] != 0 or r[1] != 0, r[0], r[1]))
        return rects

    def screenshot(self, monitor: int = 0):
        from PIL import ImageGrab
        img = ImageGrab.grab(all_screens=True)   # every monitor, as one image
        vx, vy = self.user32.GetSystemMetrics(76), self.user32.GetSystemMetrics(77)
        self.origin = (vx, vy)
        mons = self.monitors()
        if monitor and 1 <= monitor <= len(mons):
            l, t, r, b = mons[monitor - 1]
            img = img.crop((l - vx, t - vy, r - vx, b - vy))
            self.origin = (l, t)
        scale = max(1.0, img.width / MAX_SHOT_WIDTH)
        if scale > 1:
            img = img.resize((int(img.width / scale), int(img.height / scale)))
        self.scale = scale
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=80)    # ~5-10x smaller than PNG, text stays readable
        return Screenshot(base64.b64encode(buf.getvalue()).decode(), img.width, img.height, scale)

    def active_window_title(self) -> str:
        hwnd = self.user32.GetForegroundWindow()
        n = self.user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        self.user32.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value

    def click(self, x, y, button="left", clicks=1):
        rx, ry = self._real(x, y)
        self.pg.click(rx, ry, clicks=clicks, interval=0.08, button=button)

    def move(self, x, y):
        self.pg.moveTo(*self._real(x, y), duration=0.15)

    def drag(self, x1, y1, x2, y2):
        self.pg.moveTo(*self._real(x1, y1))
        self.pg.dragTo(*self._real(x2, y2), duration=0.4, button="left")

    def type_text(self, text):
        # Paste via clipboard: reliable for any characters/keyboard layout; restore clipboard afterwards.
        old = self.get_clipboard()
        self.set_clipboard(text)
        self.pg.hotkey("ctrl", "v")
        time.sleep(0.25)
        self.set_clipboard(old)

    def hotkey(self, keys):
        self.pg.hotkey(*[k.lower() for k in keys])

    def scroll(self, amount, x=None, y=None):
        if x is not None and y is not None:
            self.pg.moveTo(*self._real(x, y))
        self.pg.scroll(int(amount) * 120)

    def windows(self):
        import pygetwindow as gw
        out = []
        for w in gw.getAllWindows():
            if w.title.strip() and w.visible and w.width > 50:
                out.append({"title": w.title, "active": w.isActive, "minimized": w.isMinimized,
                            "x": w.left, "y": w.top, "w": w.width, "h": w.height})
        return out

    def _find(self, title_contains):
        import pygetwindow as gw
        t = title_contains.lower()
        for w in gw.getAllWindows():
            if t in w.title.lower() and w.title.strip():
                return w
        return None

    def focus_window(self, title_contains):
        w = self._find(title_contains)
        if not w:
            return None
        try:
            if w.isMinimized:
                w.restore()
            # Windows refuses SetForegroundWindow from background processes unless a key event happened.
            self.pg.press("alt")
            w.activate()
        except Exception:
            pass
        return w.title

    def window_action(self, title_contains, action):
        w = self._find(title_contains)
        if not w:
            return None
        {"minimize": w.minimize, "maximize": w.maximize, "restore": w.restore, "close": w.close}[action]()
        return w.title

    def get_clipboard(self):
        import pyperclip
        try:
            return pyperclip.paste()
        except Exception:
            return ""

    def set_clipboard(self, text):
        import pyperclip
        pyperclip.copy(text)

    def launch(self, target):
        if sys.platform == "win32":
            subprocess.Popen(["cmd", "/c", "start", "", target], creationflags=0x08000000)
        else:
            subprocess.Popen(["xdg-open", target])


class MockController(ComputerController):
    """Records actions; used in tests and JARVIS_MOCK_COMPUTER mode."""

    def __init__(self):
        self.log: list[tuple] = []
        self.clipboard = ""
        self.open_windows = [{"title": "Desktop", "active": True, "minimized": False}]

    def screenshot(self, monitor: int = 0):
        self.log.append(("screenshot", monitor))
        png = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()
        return Screenshot(png, 1280, 720, 1.0, "image/png")

    def click(self, x, y, button="left", clicks=1): self.log.append(("click", x, y, button, clicks))
    def move(self, x, y): self.log.append(("move", x, y))
    def drag(self, x1, y1, x2, y2): self.log.append(("drag", x1, y1, x2, y2))
    def type_text(self, text): self.log.append(("type", text))
    def hotkey(self, keys): self.log.append(("hotkey", tuple(keys)))
    def scroll(self, amount, x=None, y=None): self.log.append(("scroll", amount))
    def windows(self): return list(self.open_windows)

    def active_window_title(self):
        active = [w for w in self.open_windows if w.get("active")]
        return active[-1]["title"] if active else ""

    def focus_window(self, title_contains):
        for w in self.open_windows:
            if title_contains.lower() in w["title"].lower():
                return w["title"]
        return None

    def window_action(self, title_contains, action):
        self.log.append(("window", title_contains, action))
        return self.focus_window(title_contains)

    def get_clipboard(self): return self.clipboard
    def set_clipboard(self, text): self.clipboard = text

    def launch(self, target):
        self.log.append(("launch", target))
        self.open_windows.append({"title": f"Untitled - {target.title()}", "active": True, "minimized": False})
