"""API keys and tokens, encrypted with Windows DPAPI (CryptProtectData, bound to your Windows account).

The file data/secrets.bin is unreadable from any other Windows account or machine. Values are never sent to the UI.
The UI only sees which keys are set. On load, known provider keys are exported into os.environ for the SDKs.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import threading

from ..config import DATA_DIR

KNOWN = {
    "OPENAI_API_KEY": "OpenAI API key (second-opinion model, consult_model)",
    "ANTHROPIC_API_KEY": "Anthropic API key (optional; JARVIS normally uses your Claude Code login)",
    "HOME_ASSISTANT_TOKEN": "Home Assistant long-lived access token",
}
_PATH = DATA_DIR / "secrets.bin"
_lock = threading.Lock()


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _crypt(data: bytes, protect: bool) -> bytes:
    if os.name != "nt":
        raise RuntimeError("Secure key storage needs Windows DPAPI.")
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = _Blob()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if protect:
        ok = fn(ctypes.byref(blob_in), "jarvis", None, None, None, 0x1, ctypes.byref(blob_out))
    else:
        ok = fn(ctypes.byref(blob_in), None, None, None, None, 0x1, ctypes.byref(blob_out))
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _load() -> dict[str, str]:
    if not _PATH.exists():
        return {}
    try:
        return json.loads(_crypt(_PATH.read_bytes(), False).decode("utf-8"))
    except Exception as e:
        print(f"[secrets] could not decrypt secrets.bin: {e}")
        return {}


def get(name: str) -> str | None:
    with _lock:
        return _load().get(name)


def set_secret(name: str, value: str | None) -> None:
    with _lock:
        data = _load()
        if value:
            data[name] = value
        else:
            data.pop(name, None)
        _PATH.write_bytes(_crypt(json.dumps(data).encode("utf-8"), True))
    if name in KNOWN:
        if value:
            os.environ[name] = value
        else:
            os.environ.pop(name, None)


def status() -> dict[str, bool]:
    """Which secrets are set (from the vault or the environment). Never the values."""
    with _lock:
        data = _load()
    return {k: bool(data.get(k) or os.getenv(k)) for k in KNOWN}


def export_env() -> None:
    with _lock:
        data = _load()
    for k in KNOWN:
        if data.get(k) and not os.getenv(k):
            os.environ[k] = data[k]
