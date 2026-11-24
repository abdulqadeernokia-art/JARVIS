"""Supervisor: keeps JARVIS one word away, even when he's shut down.

  jarvis.py -> supervisor -> runs the full app (python -m jarvis_os)
     app exits with code 0 ("shut down" by voice) -> supervisor listens offline for "Jarvis" (Vosk only,
                                                     a few % CPU) -> relaunches the app, which answers "Yes, sir?"
     app exits with code 3 ("Quit completely" in the menu) -> supervisor exits too
Only one supervisor can run at a time (named mutex).
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
import time

from .config import ROOT

EXIT_SLEEP, EXIT_QUIT = 0, 3
MUTEX_NAME = "Local\\JarvisSupervisorMutex"


def single_instance() -> bool:
    ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    return ctypes.windll.kernel32.GetLastError() != 183   # ERROR_ALREADY_EXISTS


def run_app(*args: str) -> int:
    return subprocess.call([sys.executable, "-m", "jarvis_os", *args], cwd=str(ROOT))


def wait_for_name() -> None:
    """Block until 'Jarvis' is heard. Mic is released before returning."""
    import pyaudio

    from .voice.audio import CHUNK, RATE, WordSpotter
    spotter = WordSpotter()
    pa = pyaudio.PyAudio()
    stream = pa.open(format=pyaudio.paInt16, channels=1, rate=RATE, input=True, frames_per_buffer=CHUNK)
    print("[supervisor] sleeping. Say 'Jarvis' to wake me.", flush=True)
    try:
        while True:
            if spotter.feed(stream.read(CHUNK, exception_on_overflow=False)):
                print("[supervisor] heard 'Jarvis'. Waking up.", flush=True)
                try:
                    import winsound
                    winsound.Beep(880, 60)
                    winsound.Beep(1320, 80)
                except Exception:
                    pass
                return
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()


def main(start_asleep: bool = False) -> None:
    if not single_instance():
        print("[supervisor] JARVIS is already running.")
        return
    args: tuple[str, ...] = ()
    if start_asleep:
        wait_for_name()
        args = ("--woken",)
    while True:
        t0 = time.time()
        code = run_app(*args)
        if code == EXIT_QUIT:
            print("[supervisor] quit completely.")
            return
        if code != EXIT_SLEEP and time.time() - t0 < 10:
            print(f"[supervisor] app crashed on start (code {code}); retrying in 30 s")
            time.sleep(30)
            args = ()
            continue
        wait_for_name()
        args = ("--woken",)


if __name__ == "__main__":
    main("--asleep" in sys.argv)
