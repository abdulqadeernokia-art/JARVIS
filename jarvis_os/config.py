"""Configuration: environment variables (secrets, mock switches) + user settings (settings.json)."""
from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def env_flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


DATA_DIR = Path(os.getenv("JARVIS_DATA_DIR", ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Mock switches: run without real services (used by tests and development).
MOCK_LLM = env_flag("JARVIS_MOCK_LLM")
MOCK_EMAIL = env_flag("JARVIS_MOCK_EMAIL")
MOCK_CALENDAR = env_flag("JARVIS_MOCK_CALENDAR")
MOCK_COMPUTER = env_flag("JARVIS_MOCK_COMPUTER")


@dataclass
class Settings:
    user_name: str = "sir"
    voice: str = "en-GB-RyanNeural"
    wake_sensitivity: float = 0.5
    hotkey: str = "ctrl+alt+j"          # global push-to-talk / wake
    follow_up_seconds: float = 10.0     # listen this long for a reply without the wake word (15 s after a question)
    trust_level: int = 2                # 0 observe .. 4 autonomous (see safety/policy.py)
    trusted_tools: list[str] = field(default_factory=list)   # auto-approved EXTERNAL tools at level 3
    always_ask_tools: list[str] = field(default_factory=list)
    model_fast: str = "claude-opus-5-5"
    model_reasoning: str = "claude-opus-5-5"
    proactive: bool = True
    briefing_time: str = "08:00"        # "" disables the daily briefing
    file_roots: list[str] = field(default_factory=lambda: [
        str(Path.home() / d) for d in ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos")])
    approval_timeout: float = 45.0
    home_assistant_url: str = ""        # e.g. http://homeassistant.local:8123 (token lives in the DPAPI vault)
    personality: str = "calm, dry British wit, concise"
    graphics_quality: str = "low"       # high | low (galaxy particle counts)

    _path = DATA_DIR / "settings.json"
    _lock = threading.Lock()

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        if cls._path.exists():
            try:
                for k, v in json.loads(cls._path.read_text("utf-8")).items():
                    if hasattr(s, k) and not k.startswith("_"):
                        setattr(s, k, v)
            except (json.JSONDecodeError, OSError):
                pass
        # Environment overrides (kept for backwards compatibility with .env)
        s.user_name = os.getenv("JARVIS_USER_NAME", s.user_name)
        s.voice = os.getenv("JARVIS_VOICE", s.voice)
        s.wake_sensitivity = float(os.getenv("JARVIS_WAKE_SENSITIVITY", s.wake_sensitivity))
        return s

    def save(self) -> None:
        with self._lock:
            data = {k: v for k, v in asdict(self).items() if not k.startswith("_")}
            self._path.write_text(json.dumps(data, indent=2), "utf-8")

    def public(self) -> dict:
        return {k: v for k, v in asdict(self).items() if not k.startswith("_")}
