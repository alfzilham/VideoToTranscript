"""Turn timestamped Whisper segments into an AI-ready text transcript."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol


class Segment(Protocol):
    """Minimal Whisper segment interface."""

    start: float
    text: str


def format_timestamp(seconds: float) -> str:
    """Format seconds as an unbounded HH:MM:SS timestamp."""
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def format_segments(segments: Iterable[Segment]) -> str:
    """Join spoken segments using one newline, ignoring empty segments."""
    return "\n".join(
        f"[{format_timestamp(segment.start)}] {segment.text.strip()}"
        for segment in segments
        if segment.text.strip()
    )
