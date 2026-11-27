from __future__ import annotations

import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from backend.downloader.schemas import FormatInfo


@dataclass
class YouTubeSource:
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
    streams: dict
    engine: object
    selected_format_id: str | None = None


class YouTubeAdapter:
    """YouTube acquisition through Pytubefix native streams; never yt-dlp."""
    platform = "youtube"

    @staticmethod
    def _library():
        try:
            from pytubefix import YouTube
        except ImportError as exc:
            raise RuntimeError("Pytubefix belum terpasang. Pasang dependensi backend dari requirements.txt.") from exc
        return YouTube

    def inspect(self, url: str) -> YouTubeSource:
        YouTube = self._library()
        video = YouTube(url)
        streams = list(video.streams)
        choices = {}
        formats = []
        for stream in streams:
            if not getattr(stream, "includes_video_track", False):
                continue
            itag = str(stream.itag)
            has_audio = bool(getattr(stream, "includes_audio_track", False))
            audio = None
            if not has_audio:
                audio_streams = [s for s in streams if getattr(s, "includes_audio_track", False) and not getattr(s, "includes_video_track", False)]
                if not audio_streams:
                    continue
                def audio_rank(candidate):
                    rate = re.search(r"([0-9.]+)", str(getattr(candidate, "abr", "0") or "0"))
                    return (float(rate.group(1)) if rate else 0, getattr(candidate, "filesize", 0) or 0)
                audio = max(audio_streams, key=audio_rank)
            container = "mkv" if audio else (getattr(stream, "subtype", "mp4") or "mp4")
            fmt_id = f"yt:{itag}"
            height = getattr(stream, "height", None)
            fps = getattr(stream, "fps", None)
            subtype = getattr(stream, "subtype", "mp4") or "mp4"
            size = (getattr(stream, "filesize", None) or 0) + ((getattr(audio, "filesize", None) or 0) if audio else 0)
            formats.append(FormatInfo(
                format_id=fmt_id, label=f"{height or '?'}p{fps or ''} · {getattr(stream, 'video_codec', None) or 'video'} · {subtype.upper()}{' + audio stream-copy' if audio else ' progressive'}",
                width=getattr(stream, "width", None), height=height, fps=fps,
                video_codec=getattr(stream, "video_codec", None),
                audio_codec=getattr(stream, "audio_codec", None) or (getattr(audio, "audio_codec", None) if audio else None),
                container=container, estimated_size_bytes=size or None, native_original=True,
            ))
            choices[fmt_id] = (stream, audio)
        if not formats:
            raise RuntimeError("Pytubefix tidak menemukan stream video yang dapat diunduh untuk URL ini.")
        formats.sort(key=lambda f: (f.height or 0, f.fps or 0, f.estimated_size_bytes or 0), reverse=True)
        best = formats[0]
        safe_title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", video.title or "YouTube video").strip(" .")[:100] or "YouTube video"
        return YouTubeSource(url, self.platform, video.title, float(video.length) if video.length else None,
                             video.thumbnail_url, formats, True, None,
                             f"{safe_title}.{best.container or 'mp4'}", None, choices, video)

    def download(self, source: YouTubeSource, destination: Path, report, cancel_event) -> str:
        fmt = source.selected_format_id or (source.formats[0].format_id if source.formats else None)
        streams = source.streams.get(fmt)
        if not streams:
            raise ValueError("Pilihan kualitas YouTube tidak ditemukan.")
        video_stream, audio_stream = streams
        # Download each native rendition; Pytubefix handles its signed CDN URLs.
        work = destination.parent / (destination.stem + ".tracks")
        work.mkdir(parents=True, exist_ok=False)
        video_path = work / f"video.{video_stream.subtype or 'mp4'}"
        audio_path = work / f"audio.{audio_stream.subtype or 'm4a'}" if audio_stream else None
        errors = []
        total_bytes = sum(getattr(s, "filesize", 0) or 0 for s in (video_stream, audio_stream) if s) or None
        completed = 0
        def worker(stream, path):
            try:
                stream_size = getattr(stream, "filesize", None) or 0
                def on_progress(_stream, _chunk, remaining):
                    if cancel_event.is_set():
                        raise InterruptedError("Unduhan dibatalkan.")
                    report(completed + max(0, stream_size - remaining), total_bytes)
                if hasattr(source.engine, "register_on_progress_callback"):
                    source.engine.register_on_progress_callback(on_progress)
                stream.download(output_path=str(work), filename=path.name)
            except Exception as exc:
                errors.append(exc)
        try:
            for stream, path in ((video_stream, video_path), *(([(audio_stream, audio_path)] if audio_stream else []))):
                if cancel_event.is_set():
                    raise InterruptedError("Unduhan dibatalkan.")
                worker(stream, path)
                if errors:
                    raise errors[0]
                if path.stat().st_size == 0:
                    raise OSError("Pytubefix menghasilkan stream kosong.")
                completed += path.stat().st_size
                report(completed, total_bytes)
            if cancel_event.is_set():
                raise InterruptedError("Unduhan dibatalkan.")
            if audio_stream:
                ffmpeg = shutil.which("ffmpeg")
                if not ffmpeg:
                    raise RuntimeError("FFmpeg diperlukan untuk menggabungkan track audio/video tanpa re-encoding.")
                proc = subprocess.Popen([ffmpeg, "-nostdin", "-y", "-i", str(video_path), "-i", str(audio_path), "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", "-f", "matroska", str(destination)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                while proc.poll() is None:
                    if cancel_event.wait(0.2):
                        proc.terminate()
                        try: proc.wait(timeout=3)
                        except subprocess.TimeoutExpired: proc.kill()
                        raise InterruptedError("Unduhan dibatalkan.")
                if proc.returncode:
                    detail = (proc.stderr.read() if proc.stderr else b"").decode("utf-8", "replace")[-1200:]
                    raise RuntimeError(f"FFmpeg stream-copy merge gagal: {detail}")
            else:
                shutil.copyfile(video_path, destination)
            report(destination.stat().st_size, destination.stat().st_size)
            return source.filename
        finally:
            shutil.rmtree(work, ignore_errors=True)
