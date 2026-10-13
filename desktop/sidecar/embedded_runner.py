"""Runs `console.app` inside the desktop app's own process.

Signal handling is no-oped: embedded, `threading.main_thread()` is Rust's
main thread, so uvicorn wrongly thinks it is on the main thread and
`signal.signal` raises from PyO3's worker. The app owns shutdown anyway.
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
