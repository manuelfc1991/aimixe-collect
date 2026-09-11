"""Background jobs for the web interface: long collection runs with a live log."""
from __future__ import annotations

import threading
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..logging_setup import now_iso


@dataclass
class Job:
    id: str
    kind: str
    language_id: str | None
    status: str = "running"            # running | finished | failed
    log: list[str] = field(default_factory=list)
    result: Any = None
    error: str | None = None
    started_at: str = field(default_factory=now_iso)
    finished_at: str | None = None
    keep: Any = None                   # server-side object kept for a follow-up job (e.g. a search report)
    progress: dict[str, Any] = field(default_factory=dict)   # latest progress snapshot (counters, active transfers)

    def say(self, message: str) -> None:
        self.log.append(message)

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "language_id": self.language_id, "status": self.status,
                "log": self.log[-400:], "result": self.result, "error": self.error, "progress": self.progress,
                "started_at": self.started_at, "finished_at": self.finished_at}


class JobManager:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()

    def start(self, kind: str, language_id: str | None, work: Callable[[Job], Any]) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, language_id=language_id)
        with self.lock:
            self.jobs[job.id] = job

        def run() -> None:
            try:
                job.result = work(job)
                job.status = "finished"
            except Exception as exc:
                job.status = "failed"
                job.error = f"{type(exc).__name__}: {exc}"
                job.log.append(traceback.format_exc()[-2000:])
            finally:
                job.finished_at = now_iso()

        threading.Thread(target=run, name=f"job-{kind}-{job.id}", daemon=True).start()
        return job

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def list(self) -> list[Job]:
        return sorted(self.jobs.values(), key=lambda j: j.started_at, reverse=True)
