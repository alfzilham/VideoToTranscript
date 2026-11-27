from __future__ import annotations

from urllib.parse import urlsplit

from backend.downloader.adapters.direct import DirectAdapter
from backend.downloader.adapters.youtube import YouTubeAdapter
from backend.downloader.adapters.twitch import TwitchAdapter
from backend.downloader.adapters.google_drive import GoogleDriveAdapter
from backend.downloader.adapters.hls_dash import HlsDashAdapter
from backend.downloader.security import validate_http_url


def detect_platform(url: str) -> str:
    validate_http_url(url)
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower().rstrip(".")
    path = parts.path.lower()
    if host == "youtube.com" or host.endswith(".youtube.com") or host == "youtu.be":
        return "youtube"
    if host == "twitch.tv" or host.endswith(".twitch.tv"):
        return "twitch"
    if host == "whop.com" or host.endswith(".whop.com"):
        return "whop"
    if host == "drive.google.com" or host.endswith(".drive.google.com") or host == "docs.google.com":
        return "google_drive"
    if path.endswith(".m3u8") or path.endswith(".mpd") or "manifest(format=mpd" in path:
        return "hls_dash"
    return "direct"


def adapter_for(platform: str):
    if platform == "direct":
        return DirectAdapter()
    if platform == "youtube":
        return YouTubeAdapter()
    if platform == "twitch":
        return TwitchAdapter()
    if platform == "google_drive":
        return GoogleDriveAdapter()
    if platform == "hls_dash":
        return HlsDashAdapter()
    return None


PLATFORM_MESSAGES = {
    "youtube": "YouTube menggunakan Pytubefix untuk stream native; pipeline transkripsi yang ada tetap menggunakan yt-dlp.",
    "twitch": "Twitch Clip dapat diunduh melalui Helix API saat User Access Token yang sesuai scope dan editor/broadcaster berwenang dikonfigurasi. VOD download langsung tidak termasuk API publik ini.",
    "whop": "Whop dikenali, tetapi file Content Library memerlukan alur resmi dan otorisasi pemilik yang belum tersedia.",
    "google_drive": "Google Drive menggunakan Drive API untuk metadata canDownload dan blob original; OAuth Desktop harus dikonfigurasi terlebih dahulu.",
    "hls_dash": "HLS/DASH VOD publik tanpa enkripsi didukung. Live, DRM, byte-range segments, dan metode SegmentBase yang tidak dikenal ditolak.",
}
