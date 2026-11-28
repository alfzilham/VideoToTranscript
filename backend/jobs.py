"""Persistent FIFO coordination for the single CPU transcription worker."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from uuid import uuid4

TERMINAL_STATES = frozenset({"done", "error", "cancelled", "interrupted"})
ACTIVE_STATES = frozenset({"downloading", "extracting", "transcribing", "cancelling"})
DEFAULT_DB = Path.home() / ".video-to-transcript" / "job-state.sqlite3"


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
    pipeline: str = "transcription"
    stage: str = "queued"
    created_at: float = 0.0
    updated_at: float = 0.0
    queue_position: int | None = None
    payload: dict | None = None


class JobBusyError(RuntimeError):
    """Retained for third-party code that imports the original exception."""


class JobStore:
    """SQLite-backed FIFO queue; exactly one transcription handler runs at a time."""

    def __init__(self, database: Path | str | None = None) -> None:
        self.database = Path(database or os.getenv("VTT_JOB_STATE_DB", str(DEFAULT_DB))).expanduser()
        self.lock = threading.RLock()
        self._worker: threading.Thread | None = None
        self._handler: Callable[[str, dict, threading.Event], None] | None = None
        self._cancel_events: dict[str, threading.Event] = {}
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    pipeline TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT,
                    transcript TEXT,
                    filename_suggestion TEXT,
                    payload_json TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            # A process cannot safely resume a stage whose in-memory worker vanished.
            now = time.time()
            connection.execute(
                "UPDATE jobs SET status='interrupted', stage='interrupted', "
                "error_message='Backend restarted before this job completed.', updated_at=? "
                "WHERE status IN ('downloading','extracting','transcribing','cancelling')",
                (now,),
            )
            connection.execute(
                "UPDATE jobs SET status='error',stage='error',error_message=?,updated_at=? WHERE status='preparing'",
                ("Job input preparation did not finish before backend restart.", now),
            )
            rows = connection.execute("SELECT id,payload_json FROM jobs WHERE status='queued'").fetchall()
            for job_id, payload_json in rows:
                payload = json.loads(payload_json or "{}")
                if not payload or not payload.get("workdir"):
                    connection.execute(
                        "UPDATE jobs SET status='error',stage='error',error_message=?,updated_at=? WHERE id=?",
                        ("Queued job has no recoverable input payload after backend restart.", now, job_id),
                    )
                    continue
                workdir = Path(payload.get("workdir", "")) if payload.get("workdir") else None
                source = Path(payload.get("source", "")) if payload.get("source") else None
                if (workdir and not workdir.is_dir()) or (source and not source.is_file()):
                    connection.execute(
                        "UPDATE jobs SET status='error',stage='error',error_message=?,updated_at=? WHERE id=?",
                        ("Queued job input is missing after backend restart.", now, job_id),
                    )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=30, isolation_level="IMMEDIATE")
        connection.row_factory = sqlite3.Row
        return connection

    @property
    def active_id(self) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id FROM jobs WHERE pipeline='transcription' AND status IN ('downloading','extracting','transcribing','cancelling') ORDER BY updated_at LIMIT 1"
            ).fetchone()
        return row["id"] if row else None

    def create(self, status: str, *, preparing: bool = False) -> Job:
        now = time.time()
        job = Job(id=str(uuid4()), status="preparing" if preparing else "queued", stage=status, progress=0, created_at=now, updated_at=now)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO jobs(id,pipeline,status,stage,progress,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (job.id, job.pipeline, job.status, job.stage, job.progress, now, now),
            )
        return job

    def enqueue(self, job_id: str, payload: dict) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE jobs SET payload_json=?,status='queued',updated_at=? WHERE id=? AND status IN ('preparing','queued')",
                (json.dumps(payload, ensure_ascii=False), time.time(), job_id),
            )
        self.start()

    def configure(self, handler: Callable[[str, dict, threading.Event], None]) -> None:
        self._handler = handler

    def start(self) -> None:
        with self.lock:
            if self._worker and self._worker.is_alive():
                return
            if self._handler is None:
                return
            self._worker = threading.Thread(target=self._run_queue, daemon=True, name="vtt-transcription-worker")
            self._worker.start()

    def _next_queued(self) -> sqlite3.Row | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT id,payload_json,stage FROM jobs WHERE pipeline='transcription' AND status='queued' ORDER BY created_at,rowid LIMIT 1"
            ).fetchone()
            if row:
                connection.execute(
                    "UPDATE jobs SET status=?,stage=?,updated_at=? WHERE id=? AND status='queued'",
                    (row["stage"], row["stage"], time.time(), row["id"]),
                )
            return row

    def _run_queue(self) -> None:
        while True:
            with self.lock:
                row = self._next_queued()
                handler = self._handler
                if row is None or handler is None:
                    self._worker = None
                    return
                job_id = row["id"]
                event = self._cancel_events.setdefault(job_id, threading.Event())
            try:
                payload = json.loads(row["payload_json"] or "{}")
                handler(job_id, payload, event)
            except Exception as exc:
                self.update(job_id, status="error", error_message=str(exc) or type(exc).__name__)
            finally:
                with self.lock:
                    self._cancel_events.pop(job_id, None)

    def get(self, job_id: str) -> Job | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                return None
            queued = connection.execute(
                "SELECT id FROM jobs WHERE pipeline=? AND status='queued' ORDER BY created_at,rowid",
                (row["pipeline"],),
            ).fetchall()
            active = connection.execute(
                "SELECT id FROM jobs WHERE pipeline=? AND status IN ('downloading','extracting','transcribing','cancelling') ORDER BY updated_at LIMIT 1",
                (row["pipeline"],),
            ).fetchone()
        positions = {item["id"]: index + 1 for index, item in enumerate(queued)}
        position = 0 if active and active["id"] == job_id else positions.get(job_id)
        return Job(
            id=row["id"], status=row["status"], progress=row["progress"], error_message=row["error_message"],
            transcript=row["transcript"], filename_suggestion=row["filename_suggestion"], pipeline=row["pipeline"],
            stage=row["stage"], created_at=row["created_at"], updated_at=row["updated_at"], queue_position=position,
            payload=json.loads(row["payload_json"] or "{}"),
        )

    def list(self) -> list[Job]:
        with self._connect() as connection:
            ids = [row["id"] for row in connection.execute(
                "SELECT id FROM jobs ORDER BY CASE WHEN status IN ('downloading','extracting','transcribing','cancelling') THEN 0 WHEN status='queued' THEN 1 ELSE 2 END,created_at,rowid"
            ).fetchall()]
        return [job for job_id in ids if (job := self.get(job_id)) is not None]

    def worker_status(self) -> dict:
        jobs = [job for job in self.list() if job.pipeline == "transcription"]
        active = next((job for job in jobs if job.status in ACTIVE_STATES), None)
        queued = [job for job in jobs if job.status == "queued"]
        return {
            "pipeline": "transcription", "concurrency": 1, "worker_available": active is None,
            "active_job": self._public(active) if active else None,
            "queue": [self._public(job) for job in queued], "queue_length": len(queued),
        }

    @staticmethod
    def _public(job: Job) -> dict:
        return {"job_id": job.id, "status": job.status, "stage": job.stage, "progress": job.progress,
                "queue_position": job.queue_position, "created_at": job.created_at, "updated_at": job.updated_at,
                "error_message": job.error_message, "pipeline": job.pipeline}

    def update(
        self,
        job_id: str,
        *,
        status: str | None = None,
        progress: int | None = None,
        stage: str | None = None,
        error_message: str | None = None,
        transcript: str | None = None,
        filename_suggestion: str | None = None,
    ) -> None:
        current = self.get(job_id)
        if current is None or current.status in TERMINAL_STATES:
            return
        next_status = status or current.status
        next_stage = stage or (status if status in ACTIVE_STATES or status in TERMINAL_STATES else current.stage)
        next_progress = current.progress if progress is None else max(0, min(100, progress))
        if next_status == "done":
            next_progress = 100
        with self._connect() as connection:
            connection.execute(
                "UPDATE jobs SET status=?,stage=?,progress=?,error_message=COALESCE(?,error_message),"
                "transcript=COALESCE(?,transcript),filename_suggestion=COALESCE(?,filename_suggestion),updated_at=? "
                "WHERE id=? AND status NOT IN ('done','error','cancelled','interrupted')",
                (next_status, next_stage, next_progress, error_message, transcript, filename_suggestion, time.time(), job_id),
            )

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if not job or job.status in TERMINAL_STATES:
            return False
        if job.status == "queued":
            with self._connect() as connection:
                result = connection.execute(
                    "UPDATE jobs SET status='cancelled',stage='cancelled',error_message=?,updated_at=? "
                    "WHERE id=? AND status='queued'",
                    ("Job dibatalkan sebelum mulai.", time.time(), job_id),
                )
            if result.rowcount:
                workdir = (job.payload or {}).get("workdir")
                if workdir:
                    import shutil
                    shutil.rmtree(workdir, ignore_errors=True)
                return True
        with self.lock:
            event = self._cancel_events.get(job_id)
            if event:
                event.set()
                self.update(job_id, status="cancelling", stage="cancelling")
                return True
        return False

    def reconcile_startup(self) -> None:
        """Wake persisted FIFO entries after app startup; active jobs were marked interrupted in __init__."""
        self.start()


store = JobStore()
