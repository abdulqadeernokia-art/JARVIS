"""Shutdown phrasing, exit codes and the supervisor's wake-from-shutdown loop."""
import pytest

from jarvis_os import supervisor
from jarvis_os.app import QUIT


@pytest.mark.parametrize("text", ["shut down", "Jarvis, shut down", "goodbye", "okay goodbye jarvis",
                                  "go offline", "power off now", "bye bye", "turn yourself off"])
def test_direct_shutdown_commands(text):
    assert QUIT.search(text)


@pytest.mark.parametrize("text", [
    "when you are completely shut down I want to call you with your name",   # the real false trigger
    "if I shut you down how can I call you back",
    "say goodbye to Sarah in the email",
    "the server will power off at midnight",
])
def test_shutdown_words_inside_sentences_do_not_quit(text):
    assert not QUIT.search(text)


def test_supervisor_relaunches_after_voice_shutdown(monkeypatch):
    calls, waits = [], []
    codes = iter([supervisor.EXIT_SLEEP, supervisor.EXIT_SLEEP, supervisor.EXIT_QUIT])
    monkeypatch.setattr(supervisor, "single_instance", lambda: True)
    monkeypatch.setattr(supervisor, "run_app", lambda *a: (calls.append(a), next(codes))[1])
    monkeypatch.setattr(supervisor, "wait_for_name", lambda: waits.append(1))
    monkeypatch.setattr(supervisor.time, "time", iter(range(0, 1000, 20)).__next__)
    supervisor.main()
    assert calls == [(), ("--woken",), ("--woken",)]     # first start normal, then woken by name
    assert len(waits) == 2                               # listened after each voice shutdown, not after quit


def test_supervisor_single_instance(monkeypatch):
    monkeypatch.setattr(supervisor, "single_instance", lambda: False)
    monkeypatch.setattr(supervisor, "run_app", lambda *a: pytest.fail("must not start a second JARVIS"))
    supervisor.main()
