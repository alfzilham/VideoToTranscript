"""Local-only FastAPI HTTP interface for the Video to Transcript pipeline."""
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.jobs import safe_filename, store
from backend.pipeline.downloader import download_youtube_audio
from backend.pipeline.extractor import extract_audio
from backend.pipeline.formatter import format_segments
from backend.pipeline.transcriber import transcribe
from backend.downloader.router import router as downloader_router
from backend.downloader.schemas import TranscribeRequest
from backend.downloader import storage as download_storage
from backend.downloader.jobs import manager as download_manager

MAX_UPLOAD_BYTES = int(os.getenv("VTT_MAX_UPLOAD_BYTES", str(2 * 1024**3)))
if MAX_UPLOAD_BYTES < 1:
    raise ValueError("VTT_MAX_UPLOAD_BYTES harus lebih besar dari nol")
ALLOWED_EXTENSIONS = frozenset({".mp4", ".mkv", ".mov", ".webm", ".mp3", ".wav"})
AUDIO_EXTENSIONS = frozenset({".mp3", ".wav"})
ORIGINS = os.getenv("VTT_FRONTEND_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")

@asynccontextmanager
async def lifespan(_app: FastAPI):
    store.reconcile_startup()
    yield


app = FastAPI(title="Video to Transcript", description="Personal localhost transcription API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in ORIGINS.split(",") if origin.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.include_router(downloader_router)


class UrlRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    model: str = "small"


def validate_youtube_url(url: str) -> bool:
    """Allow explicit YouTube domains only; reject credentials and odd ports."""
    try:
        parsed = urlsplit(url.strip())
        hostname = (parsed.hostname or "").lower()
        return (
            parsed.scheme in {"http", "https"}
            and (hostname == "youtube.com" or hostname.endswith(".youtube.com") or hostname == "youtu.be")
            and not parsed.username
            and not parsed.password
            and parsed.port in {None, 80, 443}
            and bool(parsed.path.strip("/"))
        )
    except ValueError:
        return False


def validate_model(model: str) -> None:
    if model not in {"small", "medium"}:
        raise HTTPException(status_code=422, detail="Model harus 'small' atau 'medium'.")


def start_worker(job_id: str, workdir: Path, source: Path | None, url: str | None, model: str, title: str) -> None:
    try:
        store.enqueue(job_id, {
            "workdir": str(workdir), "source": str(source) if source else None,
            "url": url, "model": model, "title": title,
        })
    except Exception as exc:
        shutil.rmtree(workdir, ignore_errors=True)
        store.update(job_id, status="error", error_message=str(exc))
        raise HTTPException(status_code=500, detail="Gagal memulai proses transkripsi.") from exc


def run_job(
    job_id: str, workdir: Path, source: Path | None, url: str | None, model: str, title: str,
    cancel_event=None,
) -> None:
    """Execute one FIFO job; terminal state and output survive backend restarts."""
    def check_cancelled() -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError("Job dibatalkan oleh client.")

    def report(progress: int, stage: str | None = None) -> None:
        check_cancelled()
        store.update(job_id, progress=progress, stage=stage)

    try:
        check_cancelled()
        if url is not None:
            store.update(job_id, status="downloading", progress=2, stage="downloading")
            source, title = download_youtube_audio(
                url, workdir, MAX_UPLOAD_BYTES,
                lambda progress: report(progress, "downloading"),
                cancel_event=cancel_event,
            )
        check_cancelled()
        if source is None:
            raise RuntimeError("Media tidak ditemukan.")

        store.update(job_id, status="extracting", progress=30, stage="extracting")
        if url is not None or source.suffix.lower() not in AUDIO_EXTENSIONS:
            audio = extract_audio(source, workdir / "audio.wav", cancel_event)
        else:
            audio = source
        check_cancelled()
        store.update(job_id, status="transcribing", progress=55, stage="transcribing")
        segments = transcribe(audio, model, lambda progress: report(progress, "transcribing"))
        check_cancelled()
        # Preserve both timestamps as the transcriber returns dict records.
        class _Part:
            def __init__(self, start: float, text: str) -> None:
                self.start = start
                self.text = text

        transcript = format_segments(_Part(float(item["start"]), str(item["text"])) for item in segments)
        store.update(
            job_id, status="done", progress=100,
            transcript=transcript, filename_suggestion=safe_filename(title),
        )
    except InterruptedError as exc:
        store.update(job_id, status="cancelled", stage="cancelled", error_message=str(exc))
    except Exception as exc:
        store.update(job_id, status="error", error_message=str(exc) or type(exc).__name__)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _execute_queued_job(job_id: str, payload: dict, cancel_event) -> None:
    run_job(
        job_id, Path(payload["workdir"]), Path(payload["source"]) if payload.get("source") else None,
        payload.get("url"), payload["model"], payload["title"], cancel_event,
    )


store.configure(_execute_queued_job)


@app.post("/api/process/url", status_code=202)
def process_url(request: UrlRequest) -> dict[str, str]:
    validate_model(request.model)
    if not validate_youtube_url(request.url):
        raise HTTPException(status_code=422, detail="URL tidak valid. Gunakan URL youtube.com atau youtu.be.")
    job = store.create("downloading", preparing=True)
    try:
        workdir = Path(tempfile.mkdtemp(prefix="vtt-"))
    except Exception as exc:
        store.update(job.id, status="error", error_message=str(exc))
        raise HTTPException(status_code=500, detail="Gagal menyiapkan folder sementara.") from exc
    start_worker(job.id, workdir, None, request.url.strip(), request.model, "youtube-video")
    return {"job_id": job.id}


@app.post("/api/process/upload", status_code=202)
async def process_upload(file: UploadFile = File(...), model: str = Form("small")) -> dict[str, str]:
    validate_model(model)
    original_name = Path((file.filename or "").replace("\\", "/")).name
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail="Format tidak didukung. Gunakan MP4, MKV, MOV, WEBM, MP3, atau WAV.",
        )
    job = store.create("extracting", preparing=True)
    workdir: Path | None = None
    try:
        workdir = Path(tempfile.mkdtemp(prefix="vtt-"))
        source = workdir / f"source{suffix}"
        size = 0
        with source.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail=f"Ukuran file melebihi batas {MAX_UPLOAD_BYTES // (1024**2)} MB.")
                await asyncio.to_thread(output.write, chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="File upload kosong.")
        start_worker(job.id, workdir, source, None, model, original_name)
        return {"job_id": job.id}
    except Exception as exc:
        if workdir is not None:
            shutil.rmtree(workdir, ignore_errors=True)
        store.update(job.id, status="error", error_message=str(exc))
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=f"Gagal membaca file upload: {exc}") from exc
    finally:
        await file.close()


@app.get("/api/status/{job_id}")
def get_status(job_id: str) -> dict:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job tidak ditemukan (server mungkin telah restart).")
    return {
        "job_id": job.id,
        "status": job.status,
        "progress": job.progress,
        "error_message": job.error_message,
        "pipeline": job.pipeline,
        "stage": job.stage,
        "queue_position": job.queue_position,
        "worker_available": store.worker_status()["worker_available"],
        "updated_at": job.updated_at,
    }


@app.get("/api/jobs")
def list_jobs() -> list[dict]:
    return [store._public(job) for job in store.list()]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    status = get_status(job_id)
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job tidak ditemukan.")
    return status | {"created_at": job.created_at}


@app.get("/api/worker/status")
def get_worker_status() -> dict:
    return {"transcription": store.worker_status(), "download": download_manager.worker_status()}


@app.post("/api/jobs/{job_id}/cancel", status_code=202)
def cancel_job(job_id: str) -> dict:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job tidak ditemukan.")
    if job.status in {"done", "error", "cancelled", "interrupted"}:
        raise HTTPException(status_code=409, detail="Job sudah berstatus terminal dan tidak dapat dibatalkan.")
    if not store.cancel(job_id):
        raise HTTPException(status_code=409, detail="Job sedang bertransisi; periksa status sebelum mencoba lagi.")
    latest = store.get(job_id)
    return {"job_id": job_id, "status": latest.status if latest else "cancelled"}


@app.get("/api/result/{job_id}")
def get_result(job_id: str) -> dict[str, str]:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job tidak ditemukan (server mungkin telah restart).")
    if job.status != "done" or job.transcript is None or job.filename_suggestion is None:
        raise HTTPException(status_code=409, detail="Transcript belum siap.")
    return {"transcript": job.transcript, "filename_suggestion": job.filename_suggestion}


@app.post("/api/downloader/transcribe/{download_id}", status_code=202)
def transcribe_download(download_id: str, request: TranscribeRequest) -> dict[str, str]:
    """Transcribe a persistent downloader result without moving or deleting it."""
    validate_model(request.model)
    manifest = download_storage.read_manifest(download_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="Video hasil unduhan tidak ditemukan.")
    source = (Path(manifest["_directory"]) / manifest["relative_path"]).resolve()
    if source.parent != Path(manifest["_directory"]).resolve() or not source.is_file():
        raise HTTPException(status_code=404, detail="File video hasil tidak tersedia.")
    job = store.create("extracting", preparing=True)
    try:
        workdir = Path(tempfile.mkdtemp(prefix="vtt-transcribe-"))
        start_worker(job.id, workdir, source, None, request.model, manifest["filename"])
    except Exception as exc:
        store.update(job.id, status="error", error_message=str(exc))
        raise HTTPException(status_code=500, detail="Gagal memulai transkripsi dari video hasil unduhan.") from exc
    return {"job_id": job.id}
