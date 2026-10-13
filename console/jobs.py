"""Long-running work (e.g. `/enrol`, minutes of RAW reads) on a thread, with a progress stream.

In memory and not durable on purpose: this is a demo driver (`docs/security.md`).
"""

from __future__ import annotations

import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Job:
    id: str
    events: queue.Queue = field(default_factory=queue.Queue)
    done: bool = False
    result: dict | None = None
    error: str | None = None

    #: So each event carries elapsed time: shows whether a slow step is progressing.
    started: float = field(default_factory=time.time)

    def emit(self, **event) -> None:
        now = time.time()
        event.setdefault("at", datetime.fromtimestamp(now, tz=timezone.utc)
                         .isoformat(timespec="milliseconds"))
        event.setdefault("elapsed", round(now - self.started, 2))
        self.events.put(event)

    def finish(self, result: dict | None = None, error: str | None = None) -> None:
        self.result, self.error, self.done = result, error, True
        self.emit(event="done", result=result, error=error)


_JOBS: dict[str, Job] = {}


def start(target) -> Job:
    """Run ``target(job)`` on a thread and return the job immediately."""
    job = Job(id=uuid.uuid4().hex[:12])
    _JOBS[job.id] = job

    def run():
        try:
            target(job)
        except Exception as error:  # a thread that dies silently is the worst case
            job.finish(error=f"{type(error).__name__}: {error}")

    threading.Thread(target=run, daemon=True).start()
    return job


def get(job_id: str) -> Job | None:
    return _JOBS.get(job_id)
