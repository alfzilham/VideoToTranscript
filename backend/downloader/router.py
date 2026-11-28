from __future__ import annotations

import mimetypes
import os
import re
import shutil
import threading
import time
from pathlib import Path
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from backend.downloader import storage
from backend.downloader.jobs import MAX_BYTES, manager
from backend.downloader.registry import PLATFORM_MESSAGES, adapter_for, detect_platform
from backend.downloader.schemas import DownloadRequest, InspectRequest, Inspection
from backend.downloader.security import UnsafeURLError

router = APIRouter(prefix="/api/downloader", tags=["video-downloader"])
INSPECTION_TTL = max(30, int(os.getenv("VTT_DOWNLOAD_INSPECTION_TTL", "900")))
_inspections: dict[str, tuple[float, dict]] = {}
_inspection_lock = threading.Lock()


def _error(status: int, code: str, message: str):
    raise HTTPException(status_code=status, detail=message, headers={"X-Error-Code": code})


def _get_inspection(inspection_id: str) -> dict:
    try:
        UUID(inspection_id)
    except ValueError:
        _error(404, "INSPECTION_EXPIRED", "Pemeriksaan sumber tidak ditemukan atau sudah kedaluwarsa.")
    with _inspection_lock:
        item = _inspections.get(inspection_id)
        if item and item[0] >= time.monotonic():
            return item[1]
        _inspections.pop(inspection_id, None)
    _error(404, "INSPECTION_EXPIRED", "Pemeriksaan sumber tidak ditemukan atau sudah kedaluwarsa. Periksa URL lagi.")


@router.post("/inspect", response_model=Inspection)
def inspect_source(request: InspectRequest):
    try:
        platform = detect_platform(request.url)
    except UnsafeURLError as exc:
        _error(422, "INVALID_URL", str(exc))
    adapter = adapter_for(platform)
    if adapter is None:
        inspection_id = str(uuid4())
        message = PLATFORM_MESSAGES.get(platform, "Sumber ini belum didukung.")
        info = {
            "url": request.url, "platform": platform, "title": None, "duration_seconds": None,
            "thumbnail_url": None, "download_available": False, "formats": [],
            "recommended_format_id": None, "message": message, "filename": None, "size_bytes": None,
            "source": None,
        }
        with _inspection_lock:
            _inspections[inspection_id] = (time.monotonic() + INSPECTION_TTL, info)
        return {key: value for key, value in info.items() if key not in {"url", "filename", "size_bytes", "source"}} | {"inspection_id": inspection_id}
    try:
        source = adapter.inspect(request.url)
    except UnsafeURLError as exc:
        _error(422, "INVALID_URL", str(exc))
    except ValueError as exc:
        _error(422, "UNSUPPORTED_PLATFORM", str(exc))
    except Exception as exc:
        _error(422, "SOURCE_UNAVAILABLE", f"Tidak dapat memeriksa URL: {exc}")
    if source.size_bytes is not None and source.size_bytes > MAX_BYTES:
        _error(413, "FILE_TOO_LARGE", "Ukuran file sumber melebihi batas unduhan yang dikonfigurasi.")
    inspection_id = str(uuid4())
    info = {
        "url": source.url, "platform": platform, "title": source.title, "duration_seconds": source.duration_seconds,
        "thumbnail_url": source.thumbnail_url, "download_available": True, "formats": source.formats or [],
        "recommended_format_id": (source.formats[0].format_id if source.formats else "original"), "message": source.message, "filename": source.filename,
        "size_bytes": source.size_bytes, "source": source,
    }
    with _inspection_lock:
        now = time.monotonic()
        for old_id, (expires, _) in list(_inspections.items()):
            if expires < now:
                del _inspections[old_id]
        _inspections[inspection_id] = (now + INSPECTION_TTL, info)
    return {
        "inspection_id": inspection_id, "platform": platform, "title": source.title,
        "duration_seconds": source.duration_seconds, "thumbnail_url": source.thumbnail_url, "download_available": True,
        "formats": source.formats or [], "recommended_format_id": (source.formats[0].format_id if source.formats else "original"), "message": source.message,
    }


@router.post("/download", status_code=202)
def download_source(request: DownloadRequest):
    info = _get_inspection(request.inspection_id)
    if not info["download_available"] or not info["source"]:
        _error(422, "DOWNLOAD_NOT_AVAILABLE", info.get("message") or "Unduhan tidak tersedia untuk sumber ini.")
    if request.format_id not in {fmt.format_id for fmt in info["formats"]}:
        _error(422, "QUALITY_UNAVAILABLE", "Pilihan kualitas tidak termasuk format yang diperiksa.")
    adapter = adapter_for(info["platform"])
    if adapter is None:
        _error(422, "DOWNLOAD_NOT_AVAILABLE", "Tidak ada adapter unduhan untuk sumber ini.")
    try:
        # Refresh public source metadata and verify it is still a direct video.
        refreshed = adapter.inspect(info["url"])
        if request.format_id not in {fmt.format_id for fmt in refreshed.formats}:
            _error(422, "QUALITY_UNAVAILABLE", "Format yang dipilih sudah tidak tersedia. Periksa ulang sumber.")
        if hasattr(refreshed, "select_format"):
            refreshed.select_format(request.format_id)
        elif hasattr(refreshed, "selected_format_id"):
            refreshed.selected_format_id = request.format_id
            selected = next(fmt for fmt in refreshed.formats if fmt.format_id == request.format_id)
            if selected.container and info["filename"]:
                stem = info["filename"].rsplit(".", 1)[0]
                info["filename"] = f"{stem}.{selected.container}"
        info["source"] = refreshed
        info["filename"] = refreshed.filename
        info["size_bytes"] = refreshed.size_bytes
        job = manager.create_and_start(info, adapter, request.format_id)
    except HTTPException:
        raise
    except RuntimeError as exc:
        if str(exc) == "JOB_BUSY":
            _error(409, "JOB_BUSY", "Downloader sedang memproses video lain. Tunggu hingga selesai.")
        raise
    except Exception as exc:
        _error(422, "SOURCE_UNAVAILABLE", f"Sumber tidak dapat diakses ulang: {exc}")
    return {"job_id": job.job_id, "status": job.status}


@router.get("/status/{job_id}")
def download_status(job_id: str):
    try:
        UUID(job_id)
    except ValueError:
        _error(404, "JOB_NOT_FOUND", "Job downloader tidak ditemukan.")
    job = manager.get(job_id)
    if not job:
        manifest = storage.read_manifest(job_id)
        if not manifest:
            _error(404, "JOB_NOT_FOUND", "Job downloader tidak ditemukan.")
        return {"job_id": job_id, "status": "done", "progress": 100, "downloaded_bytes": manifest["file_size_bytes"], "total_bytes": manifest["file_size_bytes"], "speed_bytes_per_second": None, "eta_seconds": 0, "error_code": None, "error_message": None}
    with manager.lock:
        queue_position = (manager.queue.index(job_id) + 1) if job_id in manager.queue else (0 if job_id in manager.active else None)
    worker_available = manager.worker_status()["worker_available"]
    with job.lock:
        return {
            "job_id": job.job_id, "status": job.status, "progress": job.progress,
            "downloaded_bytes": job.downloaded_bytes, "total_bytes": job.total_bytes,
            "speed_bytes_per_second": job.speed_bytes_per_second, "eta_seconds": job.eta_seconds,
            "error_code": job.error_code, "error_message": job.error_message,
            "stage": job.stage, "stage_progress": job.stage_progress, "queue_position": queue_position,
            "worker_available": worker_available, "updated_at": job.updated_at,
        }


@router.get("/result/{job_id}")
def download_result(job_id: str):
    job = manager.get(job_id)
    result = job.result if job else None
    if not result:
        manifest = storage.read_manifest(job_id)
        if manifest:
            result = {key: value for key, value in manifest.items() if not key.startswith("_") and key != "relative_path"}
    if not result:
        if job and job.status not in {"done", "error", "cancelled"}:
            _error(409, "JOB_BUSY", "Hasil unduhan belum siap.")
        _error(404, "JOB_NOT_FOUND", "Hasil unduhan tidak ditemukan.")
    return result


def _file_for_job(job_id: str) -> tuple[Path, dict]:
    try:
        UUID(job_id)
    except ValueError:
        _error(404, "JOB_NOT_FOUND", "Job downloader tidak ditemukan.")
    manifest = storage.read_manifest(job_id)
    if not manifest:
        job = manager.get(job_id)
        if job and job.status not in {"done", "error", "cancelled"}:
            _error(409, "JOB_BUSY", "Video belum selesai divalidasi.")
        _error(404, "JOB_NOT_FOUND", "Video hasil tidak ditemukan.")
    directory = Path(manifest["_directory"]).resolve()
    path = (directory / manifest["relative_path"]).resolve()
    if path.parent != directory or not path.is_file():
        _error(404, "JOB_NOT_FOUND", "File hasil tidak tersedia.")
    return path, manifest


@router.get("/file/{job_id}")
def get_video_file(job_id: str):
    path, manifest = _file_for_job(job_id)
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, filename=manifest["filename"], content_disposition_type="attachment")


def _range(value: str | None, size: int) -> tuple[int, int] | None:
    if not value:
        return None
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value.strip())
    if not match or (not match.group(1) and not match.group(2)):
        return None
    if not match.group(1):
        length = int(match.group(2))
        if length <= 0:
            return None
        return max(0, size - length), size - 1
    start = int(match.group(1))
    end = min(int(match.group(2)), size - 1) if match.group(2) else size - 1
    return (start, end) if 0 <= start <= end < size else None


@router.get("/preview/{job_id}")
def preview_video(job_id: str, request: Request):
    path, manifest = _file_for_job(job_id)
    size = path.stat().st_size
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    byte_range = _range(request.headers.get("range"), size)
    if request.headers.get("range") and not byte_range:
        return JSONResponse(status_code=416, content={"detail": "Rentang byte tidak valid."}, headers={"Content-Range": f"bytes */{size}"})
    start, end = byte_range or (0, size - 1)
    def stream():
        with path.open("rb") as source:
            source.seek(start)
            remaining = end - start + 1
            while remaining:
                chunk = source.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk
    headers = {"Accept-Ranges": "bytes", "Content-Length": str(end - start + 1), "Content-Disposition": "inline"}
    if manifest.get("filename"):
        headers["Content-Disposition"] = f"inline; filename*=UTF-8''{quote(manifest['filename'])}"
    if byte_range:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(stream(), status_code=206 if byte_range else 200, media_type=media_type, headers=headers)


@router.get("/metadata/{job_id}")
def download_metadata(job_id: str):
    _, manifest = _file_for_job(job_id)
    return {key: value for key, value in manifest.items() if not key.startswith("_") and key != "relative_path"}


@router.post("/cancel/{job_id}")
def cancel_download(job_id: str):
    if not manager.cancel(job_id):
        job = manager.get(job_id)
        if job and job.status in {"done", "error", "cancelled", "interrupted"}:
            _error(409, "CANCELLED", "Job sudah selesai dan tidak dapat dibatalkan.")
        _error(404, "JOB_NOT_FOUND", "Job downloader tidak ditemukan.")
    job = manager.get(job_id)
    return {"job_id": job_id, "status": job.status if job else "cancelled"}


@router.get("/history")
def download_history():
    return [
        {key: value for key, value in item.items() if not key.startswith("_") and key != "relative_path"}
        for item in storage.list_manifests()
    ]


@router.get("/queue")
def download_queue():
    return manager.worker_status()
