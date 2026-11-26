from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import time
from fractions import Fraction
from pathlib import Path
from threading import Event


class ValidationFailure(RuntimeError):
    pass


def _number(value):
    try:
        result = float(value)
        return result if result >= 0 else None
    except (TypeError, ValueError):
        return None


def _fps(value):
    try:
        rate = float(Fraction(value))
        return round(rate, 3) if rate > 0 else None
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def inspect_media(path: Path) -> dict:
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except FileNotFoundError as exc:
        raise ValidationFailure("FFprobe tidak ditemukan di PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise ValidationFailure("Inspeksi media melewati batas waktu.") from exc
    if probe.returncode != 0:
        raise ValidationFailure("FFprobe tidak dapat membaca file video.")
    try:
        data = json.loads(probe.stdout)
        streams = data.get("streams", [])
        video = next(item for item in streams if item.get("codec_type") == "video")
        audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
        media_format = data.get("format", {})
    except (ValueError, StopIteration, TypeError) as exc:
        raise ValidationFailure("File tidak memiliki stream video yang valid.") from exc
    return {
        "duration_seconds": _number(media_format.get("duration")) or _number(video.get("duration")),
        "width": video.get("width") if isinstance(video.get("width"), int) else None,
        "height": video.get("height") if isinstance(video.get("height"), int) else None,
        "fps": _fps(video.get("avg_frame_rate") or video.get("r_frame_rate")),
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name") if audio else None,
        "video_bitrate_bps": int(video["bit_rate"]) if str(video.get("bit_rate", "")).isdigit() else None,
        "audio_bitrate_bps": int(audio["bit_rate"]) if audio and str(audio.get("bit_rate", "")).isdigit() else None,
        "container": media_format.get("format_name"),
        "file_size_bytes": path.stat().st_size,
    }


def validate_full_decode(path: Path, cancel_event: Event | None = None) -> None:
    args = ["ffmpeg", "-v", "error", "-xerror", "-nostdin", "-i", str(path), "-f", "null", "-"]
    try:
        with tempfile.TemporaryFile() as error_output:
            process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=error_output)
            deadline = time.monotonic() + 7200
            while process.poll() is None:
                if cancel_event and cancel_event.is_set():
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    raise InterruptedError("Validasi video dibatalkan.")
                if time.monotonic() >= deadline:
                    process.kill()
                    process.wait()
                    raise ValidationFailure("Validasi decode melewati batas waktu dua jam.")
                time.sleep(0.2)
            error_output.seek(max(0, error_output.tell() - 400))
            detail = error_output.read().decode("utf-8", errors="replace").strip()
            return_code = process.returncode
    except FileNotFoundError as exc:
        raise ValidationFailure("FFmpeg tidak ditemukan di PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise ValidationFailure("Validasi decode melewati batas waktu dua jam.") from exc
    if return_code != 0:
        raise ValidationFailure(f"Validasi full decode gagal: {detail or 'decode gagal'}")


def sha256_file(path: Path, cancel_event: Event | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as media:
        for chunk in iter(lambda: media.read(1024 * 1024), b""):
            if cancel_event and cancel_event.is_set():
                raise InterruptedError("Validasi hash dibatalkan.")
            digest.update(chunk)
    return digest.hexdigest()
