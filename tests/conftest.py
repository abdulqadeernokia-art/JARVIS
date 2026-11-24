import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis_os.config import Settings  # noqa: E402
from jarvis_os.services import build_services  # noqa: E402


class FakeVoice:
    def __init__(self, heard=None):
        self.said, self.heard = [], list(heard or [])
        self.meeting_cb = None

    def say(self, text): self.said.append(text)
    def wait_spoken(self): pass

    def listen(self, start_timeout=6, silence=1.3, max_seconds=30):
        return self.heard.pop(0) if self.heard else ""

    def start_meeting(self, cb): self.meeting_cb = cb
    def stop_meeting(self): self.meeting_cb = None


@pytest.fixture
def settings(tmp_path):
    s = Settings()
    s.file_roots = [str(tmp_path / "files")]
    (tmp_path / "files").mkdir()
    return s


@pytest.fixture
def svc(tmp_path, settings):
    s = build_services(settings, tmp_path / "test.db", mock_email=True, mock_calendar=True, mock_computer=True)
    s.approvals.auto_decision = "approved"
    s.voice = FakeVoice()
    return s


def run(coro):
    return asyncio.run(coro)
