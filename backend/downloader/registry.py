from __future__ import annotations

from urllib.parse import urlsplit

from backend.downloader.adapters.direct import DirectAdapter
from backend.downloader.adapters.youtube import YouTubeAdapter
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
    if path.endswith(".m3u8") or path.endswith(".mpd"):
        return "hls_dash"
    return "direct"


def adapter_for(platform: str):
    if platform == "direct":
        return DirectAdapter()
    if platform == "youtube":
        return YouTubeAdapter()
    return None


PLATFORM_MESSAGES = {
    "youtube": "YouTube menggunakan Pytubefix untuk stream native; pipeline transkripsi yang ada tetap menggunakan yt-dlp.",
    "twitch": "Twitch dikenali, tetapi unduhan hanya tersedia melalui alur resmi/terotorisasi yang belum dikonfigurasi.",
    "whop": "Whop dikenali, tetapi file Content Library memerlukan alur resmi dan otorisasi pemilik yang belum tersedia.",
    "google_drive": "Google Drive dikenali, tetapi akses file original memerlukan link unduhan publik atau OAuth Drive API yang belum dikonfigurasi.",
    "hls_dash": "Manifest HLS/DASH dikenali, tetapi adapter streaming terotorisasi belum tersedia. DRM atau kontrol akses tidak akan dilewati.",
}
