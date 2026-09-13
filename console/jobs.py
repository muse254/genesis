"""Long-running work with a progress stream.

`/enrol` reads forty-odd 24-megapixel RAWs and takes minutes. A demo that
shows nothing for that long looks hung, and a presenter cannot tell a slow
enrolment from a stuck one -- so the work runs on a thread and every frame it
finishes becomes an event.

Deliberately in memory and deliberately not durable. This is a demo driver
(`docs/security.md`); a job that does not survive a restart is correct here,
and a job store that did would be one more thing to go wrong on camera.
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

    #: When the job started, so every event can carry how far into the work it
    #: happened. A label alone says what is running; a label with a clock says
    #: whether it is progressing, which is the question an operator watching a
    #: slow step is actually asking.
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
