"""Launcher for the desktop/startup shortcuts.

Starts the supervisor, which runs JARVIS and, after he's shut down by voice, keeps listening offline for
"Jarvis" to bring him back. Use --asleep to start in listening-only mode.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jarvis_os.supervisor import main  # noqa: E402

if __name__ == "__main__":
    main(start_asleep="--asleep" in sys.argv)
