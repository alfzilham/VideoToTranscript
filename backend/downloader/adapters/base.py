from __future__ import annotations

from typing import Protocol

from backend.downloader.schemas import FormatInfo


class SourceInspection(Protocol):
    url: str
    platform: str
    title: str | None
    duration_seconds: float | None
    thumbnail_url: str | None
    formats: list[FormatInfo]
    download_available: bool
    message: str | None
    filename: str | None
    size_bytes: int | None


class DownloadAdapter(Protocol):
    platform: str

    def inspect(self, url: str) -> SourceInspection: ...

    def download(self, source: SourceInspection, destination, report, cancel_event) -> str: ...
