from __future__ import annotations

import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from backend.downloader.security import open_public_response
from backend.downloader.schemas import FormatInfo

VIDEO_SUFFIXES = {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".mpeg", ".mpg", ".ts"}


@dataclass
class DirectSource:
    url: str
    platform: str = "direct"
    title: str | None = None
    duration_seconds: float | None = None
    thumbnail_url: str | None = None
    formats: list[FormatInfo] | None = None
    download_available: bool = True
    message: str | None = None
    filename: str | None = None
    size_bytes: int | None = None


def _filename(content_disposition: str | None, final_url: str, content_type: str) -> str:
    candidate = None
    if content_disposition:
        match = re.search(r"filename\*=UTF-8''([^;]+)|filename=\"?([^\";]+)", content_disposition, re.I)
        if match:
            candidate = unquote(match.group(1) or match.group(2)).replace("\\", "/").split("/")[-1]
    if not candidate:
        candidate = unquote(Path(urlsplit(final_url).path).name)
    suffix = Path(candidate or "").suffix.lower()
    if suffix not in VIDEO_SUFFIXES:
        guessed = mimetypes.guess_extension(content_type.split(";", 1)[0].strip()) or ""
        suffix = guessed if guessed in VIDEO_SUFFIXES else ".mp4"
    stem = Path(candidate or "video").stem
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", stem).strip(" .")[:100]
    if stem.upper() in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(r"(COM|LPT)[1-9]", stem.upper()):
        stem = "video"
    return f"{stem or 'video'}{suffix}"


def _disposition_filename(content_disposition: str | None) -> str | None:
    if not content_disposition:
        return None
    match = re.search(r"filename\*=UTF-8''([^;]+)|filename=\"?([^\";]+)", content_disposition, re.I)
    if not match:
        return None
    return unquote(match.group(1) or match.group(2)).replace("\\", "/").split("/")[-1]


class DirectAdapter:
    platform = "direct"

    def inspect(self, url: str) -> DirectSource:
        connection = response = None
        try:
            connection, response, final_url = open_public_response(url, "HEAD")
            if response.status in {405, 501}:
                response.close()
                connection.close()
                connection, response, final_url = open_public_response(url, "GET", {"Range": "bytes=0-0"})
            if response.status not in {200, 206}:
                raise OSError(f"Sumber mengembalikan HTTP {response.status}.")
            content_type = (response.getheader("Content-Type") or "").split(";", 1)[0].strip().lower()
            content_length = response.getheader("Content-Length")
            size = int(content_length) if content_length and content_length.isdigit() else None
            if response.status == 206:
                content_range = response.getheader("Content-Range", "")
                match = re.search(r"/([0-9]+)$", content_range)
                if match:
                    size = int(match.group(1))
            parsed_path = unquote(urlsplit(final_url).path).lower()
            suggested_name = _disposition_filename(response.getheader("Content-Disposition"))
            if not (content_type.startswith("video/") or Path(parsed_path).suffix in VIDEO_SUFFIXES or Path(suggested_name or "").suffix.lower() in VIDEO_SUFFIXES):
                raise ValueError("URL ini tidak menunjuk ke file video langsung yang dikenali.")
            filename = _filename(response.getheader("Content-Disposition"), final_url, content_type)
            source_name = suggested_name or Path(parsed_path).name
            title = Path(source_name).stem if source_name else None
            return DirectSource(
                url=url,
                title=title,
                formats=[FormatInfo(format_id="original", label="Original file (metadata diperiksa setelah unduhan)", estimated_size_bytes=size, native_original=True)],
                filename=filename,
                size_bytes=size,
                message="Detail codec, resolusi, dan frame rate belum diketahui sampai file asli diunduh dan diperiksa.",
            )
        finally:
            if response:
                response.close()
            if connection:
                connection.close()

    def download(self, source: DirectSource, destination: Path, report, cancel_event) -> str:
        connection = response = None
        try:
            connection, response, _ = open_public_response(source.url, "GET")
            if response.status not in {200, 206}:
                raise OSError(f"Sumber tidak lagi tersedia (HTTP {response.status}).")
            total_header = response.getheader("Content-Length")
            total = int(total_header) if total_header and total_header.isdigit() else source.size_bytes
            downloaded = 0
            with destination.open("wb") as output:
                while True:
                    if cancel_event.is_set():
                        raise InterruptedError("Unduhan dibatalkan.")
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    downloaded += len(chunk)
                    output.write(chunk)
                    report(downloaded, total)
            if downloaded == 0 or (total is not None and downloaded != total):
                raise OSError("Unduhan tidak lengkap; ukuran file berbeda dari sumber.")
            return source.filename or destination.name
        finally:
            if response:
                response.close()
            if connection:
                connection.close()
