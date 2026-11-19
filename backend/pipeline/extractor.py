"""ffmpeg conversion to the mono PCM WAV input preferred by Whisper."""
from __future__ import annotations

import subprocess
from pathlib import Path


class ExtractionFailure(RuntimeError):
    """Audio could not be extracted from the selected media."""


def extract_audio(source: Path, destination: Path) -> Path:
    """Run ffmpeg without a shell, producing 16 kHz mono PCM WAV."""
    cmd = [
        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
        "-i", str(source), "-vn", "-ac", "1", "-ar", "16000",
        "-c:a", "pcm_s16le", str(destination),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=7200, check=False)
    except FileNotFoundError as exc:
        raise ExtractionFailure("ffmpeg tidak ditemukan di PATH. Instal ffmpeg terlebih dahulu.") from exc
    except subprocess.TimeoutExpired as exc:
        raise ExtractionFailure("Ekstraksi audio melewati batas waktu dua jam.") from exc
    if result.returncode != 0 or not destination.is_file() or destination.stat().st_size == 0:
        detail = result.stderr.strip()[-700:] if result.stderr else "Audio tidak ditemukan."
        raise ExtractionFailure(f"Ekstraksi audio gagal: {detail}")
    return destination
