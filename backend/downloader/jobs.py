from __future__ import annotations

import os
import json
import shutil
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from backend.downloader import storage
from backend.downloader.validator import ValidationFailure, inspect_media, sha256_file, validate_full_decode

MAX_BYTES = int(os.getenv("VTT_DOWNLOAD_MAX_BYTES", str(10 * 1024**3)))


@dataclass
class DownloadJob:
    job_id: str
    status: str = "queued"
    progress: int | None = 0
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    speed_bytes_per_second: int | None = None
    eta_seconds: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    result: dict | None = None
    stage: str = "queued"
    stage_progress: int | None = None
    queue_position: int | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    last_report: float = field(default_factory=time.monotonic)
    last_bytes: int = 0


class DownloadJobManager:
    def __init__(self):
        self.jobs: dict[str, DownloadJob] = {}
        self.active: set[str] = set()
        self.queue: list[str] = []
        self.pending: dict[str, tuple[dict, object, str]] = {}
        self.lock = threading.Lock()
        self.worker: threading.Thread | None = None
        self._recover_persisted_jobs()

    @property
    def concurrency(self) -> int:
        return 1

    @property
    def state_dir(self) -> Path:
        return storage.ROOT / ".jobs"

    def _persist(self, job: DownloadJob) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "job_id": job.job_id, "status": job.status, "stage": job.stage, "progress": job.progress,
            "stage_progress": job.stage_progress,
            "downloaded_bytes": job.downloaded_bytes, "total_bytes": job.total_bytes,
            "error_code": job.error_code, "error_message": job.error_message,
            "created_at": job.created_at, "updated_at": job.updated_at,
        }
        target = self.state_dir / f"{job.job_id}.json"
        temp = self.state_dir / f"{job.job_id}.json.tmp"
        temp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, target)

    def _recover_persisted_jobs(self) -> None:
        if not self.state_dir.is_dir():
            return
        for path in self.state_dir.glob("*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                if record.get("status") not in {"done", "error", "cancelled", "interrupted"}:
                    record.update(status="interrupted", stage="interrupted", progress=None,
                                  error_code="BACKEND_RESTARTED",
                                  error_message="Backend restarted before this download completed.", updated_at=time.time())
                    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
                job = DownloadJob(
                    job_id=record["job_id"], status=record["status"], stage=record.get("stage", record["status"]),
                    stage_progress=record.get("stage_progress"),
                    progress=record.get("progress"), downloaded_bytes=record.get("downloaded_bytes", 0),
                    total_bytes=record.get("total_bytes"), error_code=record.get("error_code"),
                    error_message=record.get("error_message"), created_at=record.get("created_at", time.time()),
                    updated_at=record.get("updated_at", time.time()),
                )
                self.jobs[job.job_id] = job
            except (OSError, ValueError, KeyError, TypeError):
                continue

    def create_and_start(self, inspection: dict, adapter, format_id: str) -> DownloadJob:
        with self.lock:
            job_id = str(uuid4())
            job = DownloadJob(job_id=job_id, total_bytes=inspection.get("size_bytes"))
            self.jobs[job_id] = job
            self.queue.append(job_id)
            job.queue_position = len(self.queue)
            self.pending[job_id] = (inspection, adapter, format_id)
            self._persist(job)
            if self.worker is None or not self.worker.is_alive():
                self.worker = threading.Thread(target=self._worker_loop, daemon=True, name="vtt-download-worker")
                self.worker.start()
        return job

    def _worker_loop(self) -> None:
        while True:
            with self.lock:
                while self.queue and self.queue[0] not in self.pending:
                    self.queue.pop(0)
                if not self.queue:
                    self.worker = None
                    return
                job_id = self.queue.pop(0)
                job = self.jobs[job_id]
                payload = self.pending.pop(job_id)
                self.active.add(job_id)
                job.queue_position = 0
                self._persist(job)
                self._refresh_queue_positions_locked()
            self._run(job, *payload)
            with self.lock:
                self.active.discard(job_id)
                self._refresh_queue_positions_locked()

    def _refresh_queue_positions_locked(self) -> None:
        for position, queued_id in enumerate(self.queue, start=1):
            queued_job = self.jobs.get(queued_id)
            if queued_job:
                queued_job.queue_position = position
                queued_job.updated_at = time.time()
                self._persist(queued_job)

    def _set_stage(self, job: DownloadJob, stage: str, status: str | None = None) -> None:
        with job.lock:
            job.stage = stage
            job.stage_progress = 0 if stage == "muxing" else None
            if status:
                job.status = status
            job.updated_at = time.time()
        self._persist(job)

    def _set_stage_progress(self, job: DownloadJob, progress: int) -> None:
        with job.lock:
            job.stage_progress = max(0, min(99, progress))
            job.updated_at = time.time()
        self._persist(job)

    def _progress(self, job: DownloadJob, downloaded: int, total: int | None) -> None:
        if downloaded > MAX_BYTES:
            raise ValueError("FILE_TOO_LARGE")
        free = shutil.disk_usage(storage.ROOT).free
        if free < 32 * 1024**2 or (total is not None and total - downloaded > free):
            raise OSError("INSUFFICIENT_DISK_SPACE")
        now = time.monotonic()
        with job.lock:
            elapsed = max(now - job.last_report, 0.001)
            delta = max(downloaded - job.last_bytes, 0)
            speed = int(delta / elapsed)
            job.downloaded_bytes = downloaded
            job.total_bytes = total
            job.speed_bytes_per_second = speed or job.speed_bytes_per_second
            job.eta_seconds = max(0, int((total - downloaded) / speed)) if total and speed else None
            job.progress = min(99, int(downloaded * 100 / total)) if total else None
            job.status = "downloading"
            job.stage = "downloading"
            job.stage_progress = None
            job.updated_at = now
            job.last_bytes = downloaded
            job.last_report = now
        self._persist(job)

    class _Reporter:
        def __init__(self, manager, job):
            self.manager, self.job = manager, job

        def __call__(self, downloaded, total):
            self.manager._progress(self.job, downloaded, total)

        def set_stage(self, stage):
            self.manager._set_stage(self.job, stage, stage)

        def set_stage_progress(self, progress):
            self.manager._set_stage_progress(self.job, progress)

    def _run(self, job: DownloadJob, inspection: dict, adapter, format_id: str) -> None:
        directory = None
        partial = None
        try:
            if job.cancel_event.is_set():
                raise InterruptedError("Unduhan dibatalkan.")
            size = inspection.get("size_bytes")
            if size is not None and size > MAX_BYTES:
                raise ValueError("FILE_TOO_LARGE")
            storage.ROOT.mkdir(parents=True, exist_ok=True)
            available = shutil.disk_usage(storage.ROOT).free
            if size is not None and size + 128 * 1024**2 > available:
                raise OSError("INSUFFICIENT_DISK_SPACE")
            directory = storage.ROOT / datetime.now().date().isoformat() / job.job_id
            directory.mkdir(parents=True, exist_ok=False)
            filename = storage.safe_media_filename(inspection.get("filename") or f"{inspection.get('title') or 'video'}.mp4")
            target = directory / filename
            partial = directory / f"{filename}.part"
            self._set_stage(job, "downloading", "downloading")
            adapter.download(inspection["source"], partial, self._Reporter(self, job), job.cancel_event)
            if job.cancel_event.is_set():
                raise InterruptedError("Unduhan dibatalkan.")
            actual_size = partial.stat().st_size
            if actual_size > MAX_BYTES:
                raise ValueError("FILE_TOO_LARGE")
            if inspection.get("size_bytes") is not None and actual_size != inspection["size_bytes"]:
                raise ValueError("VALIDATION_FAILED")
            if actual_size == 0:
                raise ValueError("VALIDATION_FAILED")
            self._set_stage(job, "validating", "validating")
            os.replace(partial, target)
            metadata = inspect_media(target)
            validate_full_decode(target, job.cancel_event)
            if job.cancel_event.is_set():
                raise InterruptedError("Unduhan dibatalkan.")
            sha = sha256_file(target, job.cancel_event)
            if job.cancel_event.is_set():
                raise InterruptedError("Unduhan dibatalkan.")
            result = {
                "job_id": job.job_id,
                "filename": filename,
                "title": inspection.get("title"),
                "platform": inspection["platform"],
                "file_size_bytes": target.stat().st_size,
                **metadata,
                "acquisition_method": "original_file",
                "reencoded": False,
                "full_decode_passed": True,
                "sha256": sha,
                "file_url": f"/api/downloader/file/{job.job_id}",
                "preview_url": f"/api/downloader/preview/{job.job_id}",
                "status": "done",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "relative_path": filename,
                "manifest_schema": 1,
            }
            storage.save_manifest(directory, result)
            with job.lock:
                job.result = result
                job.status = "done"
                job.progress = 100
                job.downloaded_bytes = actual_size
                job.total_bytes = actual_size
                job.error_code = None
                job.error_message = None
                job.stage = "done"
                job.queue_position = None
                job.updated_at = time.time()
            self._persist(job)
        except InterruptedError as exc:
            if directory:
                shutil.rmtree(directory, ignore_errors=True)
            with job.lock:
                job.status = "cancelled"
                job.progress = None
                job.error_code = "CANCELLED"
                job.error_message = str(exc)
                job.stage = "cancelled"
                job.queue_position = None
                job.updated_at = time.time()
            self._persist(job)
        except Exception as exc:
            if directory:
                shutil.rmtree(directory, ignore_errors=True)
            code = "VALIDATION_FAILED" if isinstance(exc, ValidationFailure) else str(exc) if str(exc) in {"FILE_TOO_LARGE", "INSUFFICIENT_DISK_SPACE", "VALIDATION_FAILED"} else "DOWNLOAD_FAILED"
            messages = {
                "FILE_TOO_LARGE": "File melebihi batas ukuran unduhan yang dikonfigurasi.",
                "INSUFFICIENT_DISK_SPACE": "Ruang disk tidak cukup untuk menyimpan file dan memvalidasinya.",
                "VALIDATION_FAILED": "File tidak lengkap atau berbeda dari ukuran sumber yang diperiksa.",
            }
            with job.lock:
                job.status = "error"
                job.error_code = code
                job.error_message = messages.get(code, str(exc) or "Unduhan gagal.")
                job.stage = "error"
                job.queue_position = None
                job.updated_at = time.time()
            self._persist(job)
        finally:
            pass

    def get(self, job_id: str) -> DownloadJob | None:
        with self.lock:
            job = self.jobs.get(job_id)
        if job:
            if job.status == "queued":
                with self.lock:
                    job.queue_position = self.queue.index(job_id) + 1 if job_id in self.queue else job.queue_position
            return job
        try:
            record = json.loads((self.state_dir / f"{job_id}.json").read_text(encoding="utf-8"))
            return DownloadJob(
                job_id=record["job_id"], status=record["status"], stage=record.get("stage", record["status"]),
                stage_progress=record.get("stage_progress"),
                progress=record.get("progress"), downloaded_bytes=record.get("downloaded_bytes", 0),
                total_bytes=record.get("total_bytes"), error_code=record.get("error_code"),
                error_message=record.get("error_message"), created_at=record.get("created_at", time.time()),
                updated_at=record.get("updated_at", time.time()),
            )
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def worker_status(self) -> dict:
        with self.lock:
            active = self.jobs[next(iter(self.active))] if self.active else None
            queue = [self.jobs[job_id] for job_id in self.queue if job_id in self.jobs]
            return {
                "pipeline": "download", "concurrency": 1, "worker_available": active is None,
                "active_job": self._public(active) if active else None,
                "queue": [self._public(job) for job in queue], "queue_length": len(queue),
            }

    @staticmethod
    def _public(job: DownloadJob) -> dict:
        return {"job_id": job.job_id, "status": job.status, "stage": job.stage,
                "progress": job.progress, "stage_progress": job.stage_progress,
                "queue_position": job.queue_position,
                "downloaded_bytes": job.downloaded_bytes, "total_bytes": job.total_bytes,
                "error_code": job.error_code, "error_message": job.error_message,
                "created_at": job.created_at, "updated_at": job.updated_at}

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if not job or job.status in {"done", "error", "cancelled", "interrupted"}:
            return False
        with self.lock:
            if job_id in self.pending:
                self.pending.pop(job_id, None)
                if job_id in self.queue:
                    self.queue.remove(job_id)
                with job.lock:
                    job.status = "cancelled"
                    job.stage = "cancelled"
                    job.progress = None
                    job.queue_position = None
                    job.error_code = "CANCELLED"
                    job.error_message = "Job dibatalkan sebelum mulai."
                    job.updated_at = time.time()
                self._persist(job)
                self._refresh_queue_positions_locked()
                return True
        job.cancel_event.set()
        return True


manager = DownloadJobManager()
