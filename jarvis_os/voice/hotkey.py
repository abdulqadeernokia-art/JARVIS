"""Global hotkey (works while other apps have focus) via the Win32 RegisterHotKey API. No extra dependencies."""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import threading
from typing import Callable

MODS = {"alt": 0x1, "ctrl": 0x2, "control": 0x2, "shift": 0x4, "win": 0x8}
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312


def parse(combo: str) -> tuple[int, int]:
    mods, vk = 0, None
    for part in combo.lower().replace(" ", "").split("+"):
        if part in MODS:
            mods |= MODS[part]
        elif len(part) == 1:
            vk = ord(part.upper())
        elif part.startswith("f") and part[1:].isdigit():
            vk = 0x6F + int(part[1:])
        elif part == "space":
            vk = 0x20
    if vk is None:
        raise ValueError(f"bad hotkey {combo!r}")
    return mods | MOD_NOREPEAT, vk


def start_hotkey(combo: str, callback: Callable[[], None]) -> bool:
    mods, vk = parse(combo)
    ok = threading.Event()
    result = {"ok": False}

    def loop():
        user32 = ctypes.windll.user32
        result["ok"] = bool(user32.RegisterHotKey(None, 1, mods, vk))
        ok.set()
        if not result["ok"]:
            return
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == WM_HOTKEY:
                callback()

    threading.Thread(target=loop, daemon=True, name="hotkey").start()
    ok.wait(2)
    return result["ok"]
