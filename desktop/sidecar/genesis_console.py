"""Entry point for the desktop app's backend.

Runs the console API on loopback. The Tauri shell sets the data paths and the
allowed origins through the environment (`desktop/src-tauri/src/lib.rs`), and
PyInstaller freezes this file into the `genesis-console` sidecar.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

if not getattr(sys, "frozen", False):
    # Run from a checkout: make the repository importable.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import uvicorn  # noqa: E402

from console.app import app  # noqa: E402


def _exit_with_parent() -> None:
    """Exit when stdin closes.

    The app holds our stdin open for as long as it runs. However it ends --
    quit, crash, force-kill -- the pipe closes, and a backend that outlived it
    would keep holding the port and the reference in memory. PyInstaller's
    one-file bootloader also runs us as a child process, so killing the
    process the app started does not by itself reach this one.
    """
    try:
        while sys.stdin.buffer.read(1024):
            pass
    finally:
        os._exit(0)


if __name__ == "__main__":
    if os.environ.get("GENESIS_EXIT_WITH_PARENT") == "1":
        threading.Thread(target=_exit_with_parent, daemon=True).start()
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ.get("GENESIS_CONSOLE_PORT", "8100")),
        log_level="info",
    )
