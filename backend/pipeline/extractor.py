"""ffmpeg conversion to the mono PCM WAV input preferred by Whisper."""
from __future__ import annotations

import subprocess
import tempfile
import time
from pathlib import Path
from threading import Event


class ExtractionFailure(RuntimeError):
    """Audio could not be extracted from the selected media."""


def extract_audio(source: Path, destination: Path, cancel_event: Event | None = None) -> Path:
    """Run cancellable ffmpeg without a shell, producing 16 kHz mono PCM WAV."""
    cmd = [
        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
        "-i", str(source), "-vn", "-ac", "1", "-ar", "16000",
        "-c:a", "pcm_s16le", str(destination),
    ]
    try:
        with tempfile.TemporaryFile() as error_log:
            process = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=error_log)
            deadline = time.monotonic() + 7200
            while process.poll() is None:
                if cancel_event and cancel_event.wait(0.2):
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    raise InterruptedError("Ekstraksi audio dibatalkan.")
                if time.monotonic() >= deadline:
                    process.kill()
                    process.wait()
                    raise ExtractionFailure("Ekstraksi audio melewati batas waktu dua jam.")
            error_log.flush()
            error_log.seek(max(0, error_log.tell() - 700))
            detail = error_log.read().decode("utf-8", "replace").strip()
            return_code = process.returncode
    except FileNotFoundError as exc:
        raise ExtractionFailure("ffmpeg tidak ditemukan di PATH. Instal ffmpeg terlebih dahulu.") from exc
    if return_code != 0 or not destination.is_file() or destination.stat().st_size == 0:
        detail = detail or "Audio tidak ditemukan."
        raise ExtractionFailure(f"Ekstraksi audio gagal: {detail}")
    return destination
