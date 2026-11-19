"""CPU-only, quantized faster-whisper transcription with segment progress."""
from __future__ import annotations

import os
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

from .formatter import format_timestamp


class TranscriptionFailure(RuntimeError):
    """Whisper could not process the media."""


@lru_cache(maxsize=1)
def get_model(name: str):
    """Cache the latest selected model to avoid reloading it every job."""
    from faster_whisper import WhisperModel

    return WhisperModel(
        name,
        device="cpu",
        compute_type="int8",
        cpu_threads=max(1, min(8, os.cpu_count() or 4)),
        num_workers=1,
    )


def transcribe(
    media: Path, model_name: str, on_progress: Callable[[int], None]
) -> list[dict[str, object]]:
    """Consume the lazy Whisper segments and report time-based approximate progress."""
    if model_name not in {"small", "medium"}:
        raise TranscriptionFailure("Model Whisper tidak didukung.")
    try:
        model = get_model(model_name)
        segments, info = model.transcribe(str(media), beam_size=5)
        duration = float(info.duration or 0)
        result: list[dict[str, object]] = []
        for segment in segments:
            result.append({
                "start": float(segment.start),
                "end": float(segment.end),
                "text": segment.text,
            })
            if duration > 0:
                on_progress(min(97, 55 + int(float(segment.end) / duration * 42)))
        return result
    except Exception as exc:
        if isinstance(exc, TranscriptionFailure):
            raise
        raise TranscriptionFailure(f"Transkripsi gagal: {exc}") from exc
