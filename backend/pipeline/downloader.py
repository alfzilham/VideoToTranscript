"""Safely download a single YouTube video's audio using yt-dlp."""
from __future__ import annotations

from pathlib import Path
from threading import Event
from typing import Callable


class DownloadFailure(RuntimeError):
    """The requested YouTube media could not be downloaded."""


def download_youtube_audio(
    url: str, destination: Path, max_bytes: int, on_progress: Callable[[int], None],
    cancel_event: Event | None = None,
) -> tuple[Path, str]:
    """Download the best audio-only rendition within an isolated work folder."""
    try:
        import yt_dlp
        from yt_dlp.utils import DownloadError
    except ImportError as exc:
        raise DownloadFailure("yt-dlp belum terinstal. Jalankan pip install -r requirements.txt.") from exc

    destination.mkdir(parents=True, exist_ok=True)

    def hook(info: dict) -> None:
        if cancel_event and cancel_event.is_set():
            raise InterruptedError("Unduhan YouTube dibatalkan.")
        if info.get("status") == "finished":
            on_progress(29)
            return
        if info.get("status") != "downloading":
            return
        total = info.get("total_bytes") or info.get("total_bytes_estimate")
        current = info.get("downloaded_bytes") or 0
        if total and total > 0:
            on_progress(max(2, min(28, 2 + int(current / total * 26))))

    options = {
        "format": "bestaudio/best",
        "outtmpl": str(destination / "source.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": False,
        "max_filesize": max_bytes,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "progress_hooks": [hook],
        "nopart": False,
    }
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=True)
            if not info or not isinstance(info, dict):
                raise DownloadFailure("Video tidak dapat diakses atau tidak tersedia.")
            title = str(info.get("title") or "youtube-video")
    except DownloadError as exc:
        message = str(exc)
        if "max-filesize" in message.lower() or "larger than max" in message.lower():
            raise DownloadFailure("File video melebihi batas ukuran yang diizinkan.") from exc
        raise DownloadFailure(f"Video tidak dapat diakses: {message}") from exc

    files = [
        path for path in destination.glob("source.*")
        if path.is_file() and not path.name.endswith((".part", ".ytdl", ".temp"))
    ]
    if len(files) != 1:
        raise DownloadFailure("File audio YouTube tidak berhasil diunduh.")
    media = files[0]
    if media.stat().st_size > max_bytes:
        raise DownloadFailure("File video melebihi batas ukuran yang diizinkan.")
    return media, title
