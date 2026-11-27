from __future__ import annotations

import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from backend.downloader.adapters.direct import DirectAdapter, DirectSource
from backend.downloader.schemas import FormatInfo

API = "https://api.twitch.tv/helix"


@dataclass
class TwitchSource:
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
    variants: dict[str, DirectSource]
    selected_format_id: str | None = None


def _clip_slug(url: str) -> str:
    parts = urlsplit(url)
    segments = [segment for segment in parts.path.split("/") if segment]
    host = (parts.hostname or "").lower()
    if host in {"clips.twitch.tv", "www.clips.twitch.tv"}:
        slug = segments[0] if segments else ""
    elif host in {"twitch.tv", "www.twitch.tv", "m.twitch.tv"}:
        try:
            slug = segments[segments.index("clip") + 1]
        except (ValueError, IndexError):
            slug = ""
    else:
        slug = ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{3,128}", slug):
        raise ValueError("URL Twitch harus menunjuk ke Clip yang valid.")
    return slug


def _api_get(path: str, params: dict[str, str], client_id: str, token: str) -> dict:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{API}/{path}?{query}",
        headers={"Client-Id": client_id, "Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read(2048).decode("utf-8", "replace")
        if exc.code in {401, 403}:
            raise RuntimeError("Twitch menolak token. Gunakan User Access Token untuk editor/broadcaster yang berwenang dengan scope editor:manage:clips atau channel:manage:clips.") from exc
        raise RuntimeError(f"Twitch API mengembalikan HTTP {exc.code}: {body[:500]}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Tidak dapat terhubung ke Twitch API: {exc}") from exc


class TwitchAdapter:
    """Downloads only the official Helix clip renditions authorized for the configured user."""
    platform = "twitch"

    def __init__(self):
        self.client_id = os.getenv("VTT_TWITCH_CLIENT_ID", "").strip()
        self.token = os.getenv("VTT_TWITCH_ACCESS_TOKEN", "").strip()
        self.token_file = Path(os.getenv("VTT_TWITCH_TOKEN_FILE", "").strip() or str(Path.home() / ".video-to-transcript" / "twitch-token.json")).expanduser()

    def _configured_token(self) -> str:
        if self.token:
            return self.token
        if not self.token_file.is_file():
            raise RuntimeError("Jalankan `python -m backend.downloader.twitch_auth` untuk otorisasi resmi Twitch Device Code Flow atau tetapkan VTT_TWITCH_ACCESS_TOKEN.")
        try:
            token_data = json.loads(self.token_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"File token Twitch tidak dapat dibaca: {self.token_file}") from exc
        if token_data.get("client_id") != self.client_id:
            raise RuntimeError("VTT_TWITCH_CLIENT_ID berbeda dari Client ID yang dipakai saat otorisasi. Jalankan ulang twitch_auth untuk aplikasi yang benar.")
        if float(token_data.get("expires_at", 0)) <= time.time() + 60:
            refresh_token = token_data.get("refresh_token")
            if not refresh_token:
                raise RuntimeError("Access token Twitch kedaluwarsa tanpa refresh token. Jalankan ulang `python -m backend.downloader.twitch_auth`.")
            request = urllib.request.Request(
                "https://id.twitch.tv/oauth2/token",
                data=urllib.parse.urlencode({
                    "client_id": self.client_id,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                }).encode("ascii"),
                headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=25) as response:
                    refreshed = json.loads(response.read().decode("utf-8"))
            except Exception as exc:
                raise RuntimeError(f"Token Twitch tidak dapat diperbarui. Jalankan ulang otorisasi Twitch: {exc}") from exc
            token_data.update(refreshed)
            token_data["expires_at"] = time.time() + int(refreshed.get("expires_in", 0))
            if not token_data.get("refresh_token"):
                token_data["refresh_token"] = refresh_token
            self.token_file.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.token_file.parent, delete=False) as temp:
                temp.write(json.dumps(token_data, indent=2))
                temp_path = Path(temp.name)
            try:
                temp_path.replace(self.token_file)
            finally:
                temp_path.unlink(missing_ok=True)
        self.token = str(token_data.get("access_token", "")).strip()
        if not self.token:
            raise RuntimeError("File token Twitch tidak berisi access token; jalankan ulang otorisasi Twitch.")
        return self.token

    def inspect(self, url: str) -> TwitchSource:
        if not self.client_id:
            raise RuntimeError("Tetapkan VTT_TWITCH_CLIENT_ID dari aplikasi Twitch Developer terlebih dahulu.")
        token = self._configured_token()
        slug = _clip_slug(url)
        current_user = _api_get("users", {}, self.client_id, token).get("data", [])
        if not current_user:
            raise RuntimeError("Token Twitch tidak mengidentifikasi pengguna yang aktif.")
        editor_id = current_user[0]["id"]
        clips = _api_get("clips", {"id": slug}, self.client_id, token).get("data", [])
        if not clips:
            raise RuntimeError("Twitch tidak menemukan Clip tersebut atau pengguna ini tidak dapat mengakses metadatanya.")
        clip = clips[0]
        downloads = _api_get("clips/downloads", {
            "editor_id": editor_id,
            "broadcaster_id": clip["broadcaster_id"],
            "clip_id": clip["id"],
        }, self.client_id, token).get("data", [])
        if not downloads:
            raise RuntimeError("Twitch tidak menyediakan URL unduhan untuk Clip ini bagi pengguna yang terautentikasi.")
        item = downloads[0]
        variants: dict[str, DirectSource] = {}
        formats: list[FormatInfo] = []
        for name, label in (("landscape_download_url", "Landscape original"), ("portrait_download_url", "Portrait original")):
            media_url = item.get(name)
            if not media_url:
                continue
            direct = DirectAdapter().inspect(media_url)
            format_id = "twitch:" + name.removesuffix("_download_url")
            variants[format_id] = direct
            formats.append(FormatInfo(format_id=format_id, label=f"{label} · codec/resolusi diperiksa sesudah unduh", estimated_size_bytes=direct.size_bytes, native_original=True))
        if not formats:
            raise RuntimeError("Twitch Clip tidak memiliki rendition unduh yang tersedia.")
        chosen = formats[0]
        direct = variants[chosen.format_id]
        filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", clip.get("title") or "Twitch clip").strip(" .")[:100] or "Twitch clip"
        return TwitchSource(url, self.platform, clip.get("title"), float(clip.get("duration") or 0) or None,
                            clip.get("thumbnail_url"), formats, True, None,
                            filename + Path(direct.filename or "clip.mp4").suffix,
                            direct.size_bytes, variants, chosen.format_id)

    def select_format(self, source: TwitchSource, format_id: str) -> None:
        if format_id not in source.variants:
            raise ValueError("Rendition Twitch tidak tersedia.")
        source.selected_format_id = format_id
        direct = source.variants[format_id]
        source.size_bytes = direct.size_bytes
        suffix = Path(direct.filename or "clip.mp4").suffix
        source.filename = Path(source.filename).stem + suffix

    def download(self, source: TwitchSource, destination: Path, report, cancel_event) -> str:
        format_id = source.selected_format_id or (source.formats[0].format_id if source.formats else None)
        direct = source.variants.get(format_id or "")
        if not direct:
            raise ValueError("Rendition Twitch terpilih tidak tersedia.")
        return DirectAdapter().download(direct, destination, report, cancel_event)
