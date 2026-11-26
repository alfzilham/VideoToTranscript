from __future__ import annotations

from pydantic import BaseModel, Field


class InspectRequest(BaseModel):
    url: str = Field(min_length=1, max_length=4096)


class FormatInfo(BaseModel):
    format_id: str
    label: str
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    container: str | None = None
    estimated_size_bytes: int | None = None
    native_original: bool


class Inspection(BaseModel):
    inspection_id: str
    platform: str
    title: str | None = None
    duration_seconds: float | None = None
    thumbnail_url: str | None = None
    download_available: bool
    formats: list[FormatInfo]
    recommended_format_id: str | None = None
    message: str | None = None


class DownloadRequest(BaseModel):
    inspection_id: str
    format_id: str


class TranscribeRequest(BaseModel):
    model: str = "small"
