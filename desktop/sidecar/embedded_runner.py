"""Runs `console.app` inside the desktop app's own process.

Imported by the embedded interpreter Rust starts directly (`src-tauri/src/
lib.rs`) -- there is no second process here, unlike `genesis_console.py`,
which this supersedes for the reasons in that file's own header.

uvicorn's `Server.run()` installs SIGINT/SIGTERM handlers and does so
unconditionally once it believes it is running on the process's main thread.
That belief comes from `threading.current_thread() is threading.main_thread()`,
and that check answers wrong here: `threading.main_thread()` resolves to
whichever thread first called `Py_Initialize`, which in an embedded process
is Rust's own main thread -- not the worker thread PyO3 actually runs this
module on. So uvicorn thinks it is on the main thread when it never is, and
calling `signal.signal` from a non-main OS thread raises. `install_signal_handlers`
and `capture_signals` are the two places that matters; both are no-oped
below. Nothing here has ever needed process signals -- the app itself owns
shutdown, and killed the whole process (interpreter and all) when it quits.
"""

from __future__ import annotations

import contextlib

import uvicorn


class _NoSignalServer(uvicorn.Server):
    def install_signal_handlers(self) -> None:
        pass

    @contextlib.contextmanager
    def capture_signals(self):
        yield


def run(app, host: str, port: int) -> None:
    """Block the calling thread serving `app`. Call this from a thread PyO3
    spawned for exactly this, never from the process's real main thread."""
    config = uvicorn.Config(app, host=host, port=port, log_level="info", loop="asyncio")
    _NoSignalServer(config).run()
