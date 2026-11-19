"""Thread-safe, single-active-job state in process memory (no database)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from threading import Lock
from uuid import uuid4

TERMINAL_STATES = frozenset({"done", "error"})


def safe_filename(title: str) -> str:
    """Sanitize a source title for a portable, nonempty .txt filename."""
    base = title.replace("\\", "/").split("/")[-1]
    base = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", base)
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", base)
    base = re.sub(r"\s+", " ", base).strip(" .")[:100].rstrip(" .")
    if not base or base.upper() in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(r"(COM|LPT)[1-9]", base.upper()):
        base = "transcript"
    return f"{base}.txt"


@dataclass
class Job:
    id: str
    status: str
    progress: int = 0
    error_message: str | None = None
    transcript: str | None = None
    filename_suggestion: str | None = None


class JobBusyError(RuntimeError):
    """Another job is being uploaded or transcribed."""


@dataclass
class JobStore:
    jobs: dict[str, Job] = field(default_factory=dict)
    active_id: str | None = None
    lock: Lock = field(default_factory=Lock)

    def create(self, status: str) -> Job:
        with self.lock:
            if self.active_id is not None:
                raise JobBusyError("Ada video lain yang sedang diproses. Tunggu hingga selesai.")
            job = Job(id=str(uuid4()), status=status, progress=1)
            self.jobs[job.id] = job
            self.active_id = job.id
            return job

    def get(self, job_id: str) -> Job | None:
        with self.lock:
            existing = self.jobs.get(job_id)
            return None if existing is None else Job(**vars(existing))

    def update(
        self,
        job_id: str,
        *,
        status: str | None = None,
        progress: int | None = None,
        error_message: str | None = None,
        transcript: str | None = None,
        filename_suggestion: str | None = None,
    ) -> None:
        with self.lock:
            job = self.jobs[job_id]
            if job.status in TERMINAL_STATES:
                return
            if status is not None:
                job.status = status
            if progress is not None:
                job.progress = max(job.progress, max(0, min(100, progress)))
            if error_message is not None:
                job.error_message = error_message
            if transcript is not None:
                job.transcript = transcript
            if filename_suggestion is not None:
                job.filename_suggestion = filename_suggestion
            if job.status in TERMINAL_STATES:
                if job.status == "done":
                    job.progress = 100
                if self.active_id == job_id:
                    self.active_id = None


store = JobStore()
