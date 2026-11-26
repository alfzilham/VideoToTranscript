from __future__ import annotations

import os
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
MAX_CONCURRENT = max(1, int(os.getenv("VTT_DOWNLOAD_MAX_CONCURRENT", "1")))


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
    cancel_event: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    last_report: float = field(default_factory=time.monotonic)
    last_bytes: int = 0


class DownloadJobManager:
    def __init__(self):
        self.jobs: dict[str, DownloadJob] = {}
        self.active: set[str] = set()
        self.lock = threading.Lock()

    def create_and_start(self, inspection: dict, adapter, format_id: str) -> DownloadJob:
        with self.lock:
            if len(self.active) >= MAX_CONCURRENT:
                raise RuntimeError("JOB_BUSY")
            job_id = str(uuid4())
            job = DownloadJob(job_id=job_id, total_bytes=inspection.get("size_bytes"))
            self.jobs[job_id] = job
            self.active.add(job_id)
        thread = threading.Thread(target=self._run, args=(job, inspection, adapter, format_id), daemon=True, name=f"vtt-download-{job_id[:8]}")
        try:
            thread.start()
        except Exception:
            with self.lock:
                self.active.discard(job_id)
                self.jobs.pop(job_id, None)
            raise
        return job

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
            job.last_bytes = downloaded
            job.last_report = now

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
            job.status = "downloading"
            adapter.download(inspection["source"], partial, lambda got, total: self._progress(job, got, total), job.cancel_event)
            if job.cancel_event.is_set():
                raise InterruptedError("Unduhan dibatalkan.")
            actual_size = partial.stat().st_size
            if actual_size > MAX_BYTES:
                raise ValueError("FILE_TOO_LARGE")
            if inspection.get("size_bytes") is not None and actual_size != inspection["size_bytes"]:
                raise ValueError("VALIDATION_FAILED")
            if actual_size == 0:
                raise ValueError("VALIDATION_FAILED")
            job.status = "validating"
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
        except InterruptedError as exc:
            if directory:
                shutil.rmtree(directory, ignore_errors=True)
            with job.lock:
                job.status = "cancelled"
                job.progress = None
                job.error_code = "CANCELLED"
                job.error_message = str(exc)
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
        finally:
            with self.lock:
                self.active.discard(job.job_id)

    def get(self, job_id: str) -> DownloadJob | None:
        with self.lock:
            return self.jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if not job or job.status in {"done", "error", "cancelled"}:
            return False
        job.cancel_event.set()
        return True


manager = DownloadJobManager()
