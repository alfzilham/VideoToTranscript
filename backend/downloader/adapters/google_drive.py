from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from backend.downloader.schemas import FormatInfo

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
VIDEO_MIMES = {"video/mp4", "video/quicktime", "video/x-matroska", "video/webm", "video/x-msvideo", "video/mpeg"}


@dataclass
class DriveSource:
    url: str
    platform: str
    title: str | None
    duration_seconds: float | None
    thumbnail_url: str | None
    formats: list[FormatInfo]
    download_available: bool
    message: str | None
    filename: str
    size_bytes: int | None
    file_id: str
    metadata: dict
    service: object
    selected_format_id: str | None = None


def extract_drive_file_id(url: str) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host not in {"drive.google.com", "docs.google.com"}:
        raise ValueError("URL bukan tautan file Google Drive.")
    segments = [segment for segment in parts.path.split("/") if segment]
    candidate = None
    for marker in ("d", "file"):
        if marker in segments:
            index = segments.index(marker)
            if marker == "d" and index + 1 < len(segments):
                candidate = segments[index + 1]
            elif marker == "file" and index + 2 < len(segments) and segments[index + 1] == "d":
                candidate = segments[index + 2]
    candidate = candidate or parse_qs(parts.query).get("id", [None])[0]
    if not candidate or not re.fullmatch(r"[A-Za-z0-9_-]{10,200}", candidate):
        raise ValueError("ID file Google Drive tidak ditemukan pada URL.")
    return candidate


def _credentials():
    client_file = os.getenv("VTT_GOOGLE_DRIVE_OAUTH_CLIENT_FILE", "").strip()
    token_file = Path(os.getenv("VTT_GOOGLE_DRIVE_TOKEN_FILE", "").strip() or str(Path.home() / ".video-to-transcript" / "google-drive-token.json")).expanduser()
    if not client_file:
        raise RuntimeError("Tetapkan VTT_GOOGLE_DRIVE_OAUTH_CLIENT_FILE ke file OAuth Desktop milik proyek Google Cloud, lalu jalankan backend.downloader.google_drive_auth untuk otorisasi.")
    if not Path(client_file).expanduser().is_file():
        raise RuntimeError(f"File OAuth Desktop tidak ditemukan: {client_file}")
    if not token_file.is_file():
        raise RuntimeError(f"Token Google Drive belum ada di {token_file}. Jalankan `python -m backend.downloader.google_drive_auth` dari root proyek.")
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        credentials = Credentials.from_authorized_user_file(str(token_file), SCOPES)
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            token_file.write_text(credentials.to_json(), encoding="utf-8")
        if not credentials.valid:
            raise RuntimeError("Token Google Drive tidak valid; jalankan ulang alur OAuth proyek.")
        return credentials
    except FileNotFoundError as exc:
        raise RuntimeError(f"File OAuth Desktop tidak ditemukan: {client_file}") from exc
    except Exception as exc:
        raise RuntimeError(f"Gagal memuat otorisasi Google Drive: {exc}") from exc


class GoogleDriveAdapter:
    platform = "google_drive"

    def inspect(self, url: str) -> DriveSource:
        file_id = extract_drive_file_id(url)
        creds = _credentials()
        try:
            from googleapiclient.discovery import build
            service = build("drive", "v3", credentials=creds, cache_discovery=False)
            metadata = service.files().get(
                fileId=file_id,
                supportsAllDrives=True,
                fields="id,name,mimeType,size,webViewLink,capabilities(canDownload),videoMediaMetadata",
            ).execute()
        except Exception as exc:
            raise RuntimeError(f"Google Drive tidak dapat mengambil metadata file: {exc}") from exc
        if not metadata.get("capabilities", {}).get("canDownload", False):
            raise RuntimeError("Google Drive melaporkan file ini tidak dapat diunduh untuk akun yang terotorisasi.")
        mime = (metadata.get("mimeType") or "").lower()
        name = metadata.get("name") or "drive-video"
        if not (mime.startswith("video/") or Path(name).suffix.lower() in {".mp4", ".mov", ".mkv", ".webm", ".avi", ".mpeg", ".mpg", ".m4v"}):
            raise RuntimeError(f"File Drive bukan media video yang didukung ({mime or 'MIME tidak diketahui'}).")
        size = int(metadata["size"]) if str(metadata.get("size", "")).isdigit() else None
        media = metadata.get("videoMediaMetadata") or {}
        width = int(media["width"]) if str(media.get("width", "")).isdigit() else None
        height = int(media["height"]) if str(media.get("height", "")).isdigit() else None
        duration = float(media["durationMillis"]) / 1000 if str(media.get("durationMillis", "")).isdigit() else None
        fmt = FormatInfo(format_id="original", label=f"Original Drive file · {mime or 'video'}", width=width, height=height, container=Path(name).suffix.lstrip(".").lower() or None, estimated_size_bytes=size, native_original=True)
        return DriveSource(url, self.platform, Path(name).stem, duration, None, [fmt], True,
                           "File diambil dari blob asli Drive API tanpa ekspor/re-encoding.", name, size,
                           file_id, metadata, service, "original")

    def download(self, source: DriveSource, destination: Path, report, cancel_event) -> str:
        try:
            from googleapiclient.http import MediaIoBaseDownload
            request = source.service.files().get_media(fileId=source.file_id, supportsAllDrives=True)
            with destination.open("wb") as output:
                downloader = MediaIoBaseDownload(output, request, chunksize=1024 * 1024)
                done = False
                while not done:
                    if cancel_event.is_set():
                        raise InterruptedError("Unduhan dibatalkan.")
                    _, done = downloader.next_chunk(num_retries=2)
                    report(output.tell(), source.size_bytes)
            return source.filename
        except InterruptedError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Unduhan original Google Drive gagal: {exc}") from exc
