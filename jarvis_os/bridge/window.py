"""Control the galaxy app window (an Edge/Chrome --app window titled "JARVIS") from Python.

The window opens full screen with no title bar, so its own minimise / close buttons don't exist. The HUD's
buttons call these instead, through the bridge.
"""
from __future__ import annotations

import ctypes
import sys

TITLE = "JARVIS"
SW_MINIMIZE, SW_RESTORE = 6, 9
WM_CLOSE = 0x0010


def find_windows(title: str = TITLE) -> list[int]:
    if sys.platform != "win32":
        return []
    user32 = ctypes.windll.user32
    found: list[int] = []
    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        if buf.value == title and cls.value.startswith("Chrome_WidgetWin"):
            found.append(hwnd)
        return True

    user32.EnumWindows(proto(cb), 0)
    return found


def minimize_windows() -> int:
    hwnds = find_windows()
    for h in hwnds:
        ctypes.windll.user32.ShowWindow(h, SW_MINIMIZE)
    return len(hwnds)


def restore_windows() -> int:
    hwnds = find_windows()
    for h in hwnds:
        ctypes.windll.user32.ShowWindow(h, SW_RESTORE)
        ctypes.windll.user32.SetForegroundWindow(h)
    return len(hwnds)


def close_windows() -> int:
    hwnds = find_windows()
    for h in hwnds:
        ctypes.windll.user32.PostMessageW(h, WM_CLOSE, 0, 0)
    return len(hwnds)
