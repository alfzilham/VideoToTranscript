from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

from backend.downloader.schemas import FormatInfo
from backend.downloader.security import open_public_response

MAX_MANIFEST = 2 * 1024 * 1024
MAX_MEDIA_BYTES = int(os.getenv("VTT_DOWNLOAD_MAX_BYTES", str(10 * 1024**3)))


@dataclass
class StreamChoice:
    format_id: str
    video_url: str | None = None
    audio_url: str | None = None
    video_segments: list[str] | None = None
    audio_segments: list[str] | None = None
    video_init: str | None = None
    audio_init: str | None = None
    video_ext: str = ".ts"
    audio_ext: str = ".ts"


@dataclass
class ManifestSource:
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
    choices: dict[str, StreamChoice]
    selected_format_id: str | None = None


def _fetch(url: str, *, limit: int | None = None) -> tuple[bytes, str, dict]:
    conn = response = None
    try:
        conn, response, final_url = open_public_response(url, "GET")
        if response.status not in {200, 206}:
            raise OSError(f"Manifest/segment returned HTTP {response.status}.")
        chunks, size = [], 0
        while True:
            block = response.read(min(1024 * 1024, (limit - size + 1) if limit is not None else 1024 * 1024))
            if not block:
                break
            size += len(block)
            if limit is not None and size > limit:
                raise ValueError("Manifest exceeds the 2 MiB inspection limit.")
            chunks.append(block)
        return b"".join(chunks), final_url, dict(response.getheaders())
    finally:
        if response:
            response.close()
        if conn:
            conn.close()


def _attrs(value: str) -> dict[str, str]:
    return {k: v.strip('"').replace('""', '"') for k, v in re.findall(r'([A-Z0-9-]+)=((?:"(?:[^"]|"")*")|[^,]*)', value)}


def _playlist(url: str) -> tuple[list[str], str]:
    data, final_url, _ = _fetch(url, limit=MAX_MANIFEST)
    text = data.decode("utf-8-sig", "replace")
    if not text.lstrip().startswith("#EXTM3U"):
        raise ValueError("URL tidak mengembalikan manifest HLS yang valid.")
    if "#EXT-X-SESSION-KEY" in text:
        raise ValueError("HLS session key/encrypted media is unsupported; protected streams are not decrypted.")
    if re.search(r"#EXT-X-KEY:[^\r\n]*METHOD=(?!NONE)[A-Z0-9-]+", text):
        raise ValueError("HLS encryption is unsupported; DRM or encrypted media is not decrypted.")
    if "#EXT-X-PART:" in text or "#EXT-X-BYTERANGE:" in text:
        raise ValueError("Low-latency HLS and byte-range segment playlists are not supported yet.")
    return [line.strip() for line in text.splitlines() if line.strip()], final_url


def _parse_hls(url: str) -> tuple[list[FormatInfo], dict[str, StreamChoice], float | None]:
    lines, final_url = _playlist(url)
    variants, audio_groups = [], {}
    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-MEDIA:"):
            a = _attrs(line.split(":", 1)[1])
            if a.get("TYPE") == "AUDIO" and a.get("URI"):
                audio_groups.setdefault(a.get("GROUP-ID", ""), []).append(a)
        elif line.startswith("#EXT-X-STREAM-INF:"):
            a = _attrs(line.split(":", 1)[1])
            if i + 1 >= len(lines) or lines[i + 1].startswith("#"):
                raise ValueError("HLS master playlist has a variant without a media URI.")
            variants.append((a, urljoin(final_url, lines[i + 1])))
    if not variants:
        segments, duration, init = _media_playlist_choice(final_url)
        fmt = FormatInfo(format_id="hls:original", label="HLS original rendition", native_original=True)
        choice = StreamChoice(fmt.format_id, video_segments=segments, video_init=init or None, video_ext=".mp4" if init else ".ts")
        return [fmt], {fmt.format_id: choice}, duration
    formats, choices = [], {}
    selected_duration = None
    for index, (a, media_url) in enumerate(variants):
        resolution = re.fullmatch(r"(\d+)x(\d+)", a.get("RESOLUTION", ""))
        width, height = (int(resolution.group(1)), int(resolution.group(2))) if resolution else (None, None)
        try: fps = float(a["FRAME-RATE"]) if a.get("FRAME-RATE") else None
        except ValueError: fps = None
        try: bandwidth = int(a.get("AVERAGE-BANDWIDTH") or a.get("BANDWIDTH") or 0)
        except ValueError: bandwidth = 0
        codecs = a.get("CODECS", "")
        codec_list = [c.strip() for c in codecs.split(",") if c.strip()]
        video_codec = next((c for c in codec_list if any(k in c.lower() for k in ("avc", "vp9", "av01", "hvc", "hev"))), codec_list[0] if codec_list else None)
        audio_codec = next((c for c in codec_list if c != video_codec), None)
        group = a.get("AUDIO")
        audio_url = None
        if group and audio_groups.get(group):
            audios = audio_groups[group]
            best_audio = next((x for x in audios if x.get("DEFAULT") == "YES"), audios[0])
            audio_url = urljoin(final_url, best_audio["URI"])
        fmt_id = f"hls:{index}"
        label = f"{height}p" if height else "HLS"
        if fps: label += f"{fps:g}fps"
        if video_codec: label += f" · {video_codec}"
        if bandwidth: label += f" · {bandwidth // 1000} kbps"
        if audio_url: label += " + alternate audio"
        fmt = FormatInfo(format_id=fmt_id, label=label, width=width, height=height, fps=fps, video_codec=video_codec, audio_codec=audio_codec, estimated_size_bytes=None, native_original=True)
        segments, duration, init = _media_playlist_choice(media_url)
        audio_segments = audio_init = None
        audio_ext = ".ts"
        if audio_url:
            audio_segments, _, audio_init = _media_playlist_choice(audio_url)
            audio_ext = ".mp4" if audio_init else ".ts"
        formats.append(fmt)
        choices[fmt_id] = StreamChoice(fmt_id, video_segments=segments, audio_segments=audio_segments,
                                       video_init=init or None, audio_init=audio_init,
                                       video_ext=".mp4" if init else ".ts", audio_ext=audio_ext)
        if selected_duration is None:
            selected_duration = duration
    formats.sort(key=lambda f: (f.height or 0, f.fps or 0, _bandwidth_from_label(f.label)), reverse=True)
    return formats, choices, selected_duration


def _bandwidth_from_label(label: str) -> int:
    m = re.search(r"· (\d+) kbps", label)
    return int(m.group(1)) if m else 0


def _media_playlist_choice(url: str) -> tuple[list[str], float, str]:
    lines, final_url = _playlist(url)
    if any(line.startswith("#EXT-X-STREAM-INF") for line in lines):
        raise ValueError("Nested HLS master playlists are not supported.")
    if "#EXT-X-ENDLIST" not in lines:
        raise ValueError("Live or incomplete HLS playlists are not supported; provide a complete VOD manifest.")
    segments, duration, init, ext = [], 0.0, "", ".ts"
    for line in lines:
        if line.startswith("#EXTINF:"):
            try: duration += float(line.split(":", 1)[1].split(",", 1)[0])
            except ValueError: pass
        elif line.startswith("#EXT-X-MAP:"):
            init = _attrs(line.split(":", 1)[1]).get("URI", "")
            if not init: raise ValueError("HLS initialization section has no URI.")
            init = urljoin(final_url, init); ext = ".mp4"
        elif not line.startswith("#"):
            segment = urljoin(final_url, line); segments.append(segment)
            if Path(urlsplit(segment).path).suffix.lower() in {".m4s", ".mp4"}: ext = ".mp4"
    if not segments: raise ValueError("HLS VOD manifest contains no media segments.")
    return segments, duration, init if ext == ".mp4" else ""


def _parse_duration(value: str | None) -> float | None:
    if not value: return None
    match = re.fullmatch(r"PT(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?", value)
    if not match: return None
    h, m, s = (float(x or 0) for x in match.groups())
    return h * 3600 + m * 60 + s


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(el, name):
    return next((x for x in list(el) if _local_name(x.tag) == name), None)


def _children(el, name):
    return [x for x in list(el) if _local_name(x.tag) == name]


def _template_value(value: str, rep_id: str, bandwidth: int, number: int | None = None, time_value: int | None = None) -> str:
    value = value.replace("$$", "\0")
    pattern = re.compile(r"\$(RepresentationID|Bandwidth|Number|Time)(%0\d+d)?\$")
    def sub(match):
        key = match.group(1); spec = match.group(2)
        raw = {"RepresentationID": rep_id, "Bandwidth": bandwidth, "Number": number, "Time": time_value}.get(key)
        if raw is None: raise ValueError(f"DASH SegmentTemplate placeholder {key} cannot be expanded.")
        return spec % int(raw) if spec else str(raw)
    return pattern.sub(sub, value).replace("\0", "$")


def _dash_rep_segments(root, period, adaptation, rep, period_duration) -> tuple[list[str], str | None, str]:
    chain = [root, period, adaptation, rep]
    base = ""
    for parent in chain:
        child = _child(parent, "BaseURL")
        if child is not None and child.text:
            base = urljoin(base or root.get("_source_url", ""), child.text.strip())
    if not base: base = root.get("_source_url", "")
    rep_id = rep.get("id", "")
    bandwidth = int(rep.get("bandwidth", "0") or 0)
    template_attrs, timeline = {}, None
    for parent in chain:
        t = _child(parent, "SegmentTemplate")
        if t is not None:
            template_attrs.update(t.attrib)
            tl = _child(t, "SegmentTimeline")
            if tl is not None: timeline = tl
    seg_list = next((_child(parent, "SegmentList") for parent in reversed(chain) if _child(parent, "SegmentList") is not None), None)
    if seg_list is not None:
        init = _child(seg_list, "Initialization")
        if init is not None and init.get("range"): raise ValueError("DASH byte-range initialization is unsupported.")
        init_url = urljoin(base, init.get("sourceURL")) if init is not None and init.get("sourceURL") else None
        urls = []
        for segment in _children(seg_list, "SegmentURL"):
            if segment.get("mediaRange"): raise ValueError("DASH byte-range segments are unsupported.")
            if segment.get("media"): urls.append(urljoin(base, segment.get("media")))
        if not urls: raise ValueError("DASH SegmentList contains no media segments.")
        return urls, init_url, ".mp4"
    if template_attrs:
        media, init_template = template_attrs.get("media"), template_attrs.get("initialization")
        if not media: raise ValueError("DASH SegmentTemplate is missing media template.")
        init_url = urljoin(base, _template_value(init_template, rep_id, bandwidth)) if init_template else None
        timescale = int(template_attrs.get("timescale", "1"))
        start_number = int(template_attrs.get("startNumber", "1"))
        values = []
        if timeline is not None:
            current = 0
            timeline_items = _children(timeline, "S")
            for index, item in enumerate(timeline_items):
                d = int(item.get("d", "0")); current = int(item.get("t", current))
                repeat = int(item.get("r", "0"))
                if d <= 0: raise ValueError("DASH timeline segment duration is invalid.")
                if repeat < 0:
                    end = int(timeline_items[index + 1].get("t")) if index + 1 < len(timeline_items) and timeline_items[index + 1].get("t") else int(period_duration * timescale) if period_duration else None
                    if end is None: raise ValueError("DASH negative-repeat timeline requires a known period duration.")
                    repeat = max(0, math.ceil((end - current) / d) - 1)
                if repeat > 20000: raise ValueError("DASH timeline exceeds the segment resource limit.")
                for _ in range(repeat + 1):
                    values.append((start_number + len(values), current)); current += d
        else:
            duration = int(template_attrs.get("duration", "0"))
            if duration <= 0 or not period_duration: raise ValueError("DASH template requires duration and static period duration, or a SegmentTimeline.")
            count = math.ceil(period_duration * timescale / duration)
            if count > 20000: raise ValueError("DASH manifest exceeds the 20,000 segment limit.")
            values = [(start_number + i, i * duration) for i in range(count)]
        urls = [urljoin(base, _template_value(media, rep_id, bandwidth, number=n, time_value=t)) for n, t in values]
        if not urls: raise ValueError("DASH SegmentTemplate produced no segment URLs.")
        return urls, init_url, ".mp4"
    if Path(urlsplit(base).path).suffix.lower() in {".mp4", ".m4v", ".mkv", ".webm"}:
        return [base], None, Path(urlsplit(base).path).suffix.lower()
    raise ValueError("DASH representation has no supported SegmentList or SegmentTemplate.")


def _parse_dash(url: str) -> tuple[list[FormatInfo], dict[str, StreamChoice], float | None]:
    data, final_url, _ = _fetch(url, limit=MAX_MANIFEST)
    text = data.decode("utf-8-sig", "replace")
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper(): raise ValueError("DASH XML DTD/entity declarations are rejected.")
    try: root = ET.fromstring(text)
    except ET.ParseError as exc: raise ValueError(f"DASH MPD is not valid XML: {exc}") from exc
    if _local_name(root.tag) != "MPD": raise ValueError("URL does not contain a DASH MPD manifest.")
    root.set("_source_url", final_url)
    if root.get("type", "static") == "dynamic": raise ValueError("Live/dynamic DASH MPDs are not supported; provide a complete static VOD MPD.")
    if any(_local_name(node.tag) == "ContentProtection" for node in root.iter()): raise ValueError("DASH ContentProtection is present; protected/DRM media is rejected and not decrypted.")
    periods = _children(root, "Period")
    if len(periods) != 1: raise ValueError("Only single-period static DASH presentations are supported.")
    period = periods[0]
    period_duration = _parse_duration(period.get("duration") or root.get("mediaPresentationDuration"))
    video_reps, audio_reps = [], []
    for adaptation in _children(period, "AdaptationSet"):
        mime = adaptation.get("mimeType", "")
        content = adaptation.get("contentType", "")
        reps = _children(adaptation, "Representation")
        if content == "video" or mime.startswith("video/"):
            video_reps.extend((adaptation, rep) for rep in reps)
        elif content == "audio" or mime.startswith("audio/"):
            audio_reps.extend((adaptation, rep) for rep in reps)
    if not video_reps: raise ValueError("DASH MPD provides no video representation.")
    audio_pair = max(audio_reps, key=lambda pair: int(pair[1].get("bandwidth", "0") or 0)) if audio_reps else None
    formats, choices = [], {}
    for index, (adaptation, rep) in enumerate(video_reps):
        rep_id = rep.get("id") or str(index)
        bandwidth = int(rep.get("bandwidth", "0") or 0)
        width = int(rep.get("width", "0") or 0) or None
        height = int(rep.get("height", "0") or 0) or None
        try: fps = float(rep.get("frameRate", adaptation.get("frameRate", "0")).split("/")[0]) or None
        except ValueError: fps = None
        codec = rep.get("codecs") or adaptation.get("codecs")
        v_urls, v_init, v_ext = _dash_rep_segments(root, period, adaptation, rep, period_duration)
        a_urls = a_init = None; a_ext = ".mp4"
        if audio_pair:
            aa, ar = audio_pair
            a_urls, a_init, a_ext = _dash_rep_segments(root, period, aa, ar, period_duration)
        fmt_id = f"dash:{rep_id}:{index}"
        label = f"{height}p" if height else "DASH"
        if fps: label += f"{fps:g}fps"
        if codec: label += f" · {codec}"
        if bandwidth: label += f" · {bandwidth // 1000} kbps"
        if a_urls: label += " + separate audio"
        formats.append(FormatInfo(format_id=fmt_id, label=label, width=width, height=height, fps=fps, video_codec=codec, container="matroska", native_original=True))
        choices[fmt_id] = StreamChoice(fmt_id, video_segments=v_urls, audio_segments=a_urls, video_init=v_init,
                                      audio_init=a_init, video_ext=v_ext, audio_ext=a_ext)
    formats.sort(key=lambda f: (f.height or 0, f.fps or 0, _bandwidth_from_label(f.label)), reverse=True)
    return formats, choices, period_duration


class HlsDashAdapter:
    platform = "hls_dash"

    def inspect(self, url: str) -> ManifestSource:
        path = urlsplit(url).path.lower()
        if path.endswith(".m3u8"):
            formats, choices, duration = _parse_hls(url)
        elif path.endswith(".mpd") or "manifest(format=mpd" in path:
            formats, choices, duration = _parse_dash(url)
        else:
            raise ValueError("Manifest harus berakhiran .m3u8 atau .mpd.")
        if not formats: raise ValueError("Manifest tidak menyediakan rendition media yang didukung.")
        return ManifestSource(url, self.platform, None, duration, None, formats, True, None,
                              "stream-capture.mkv", None, choices, formats[0].format_id)

    def download(self, source: ManifestSource, destination: Path, report, cancel_event) -> str:
        fmt_id = source.selected_format_id or source.formats[0].format_id
        choice = source.choices.get(fmt_id)
        if not choice: raise ValueError("Manifest rendition yang dipilih tidak tersedia.")
        work = destination.parent / f"{destination.stem}.manifest-work"
        work.mkdir(parents=True, exist_ok=False)
        downloaded = 0
        def write_track(urls: list[str] | None, init_url: str | None, path: Path):
            nonlocal downloaded
            with path.open("wb") as output:
                resources = ([init_url] if init_url else []) + (urls or [])
                for resource in resources:
                    if cancel_event.is_set(): raise InterruptedError("Unduhan dibatalkan.")
                    conn = response = None
                    try:
                        conn, response, _ = open_public_response(resource, "GET")
                        if response.status not in {200, 206}: raise OSError(f"Segment returned HTTP {response.status}.")
                        while True:
                            if cancel_event.is_set(): raise InterruptedError("Unduhan dibatalkan.")
                            block = response.read(1024 * 1024)
                            if not block: break
                            output.write(block); downloaded += len(block)
                            if downloaded > MAX_MEDIA_BYTES: raise ValueError("FILE_TOO_LARGE")
                            report(downloaded, None)
                    finally:
                        if response: response.close()
                        if conn: conn.close()
        try:
            video_path = work / f"video{choice.video_ext}"
            write_track(choice.video_segments, choice.video_init, video_path)
            audio_path = None
            if choice.audio_segments:
                audio_path = work / f"audio{choice.audio_ext}"
                write_track(choice.audio_segments, choice.audio_init, audio_path)
            if cancel_event.is_set(): raise InterruptedError("Unduhan dibatalkan.")
            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg: raise RuntimeError("FFmpeg dibutuhkan untuk mux stream-copy.")
            command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(video_path)]
            if audio_path: command += ["-i", str(audio_path)]
            command += ["-map", "0:v?", "-map", "0:a?" if not audio_path else "1:a?", "-c", "copy", "-f", "matroska", str(destination)]
            proc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            while proc.poll() is None:
                if cancel_event.wait(0.2):
                    proc.terminate()
                    try: proc.wait(timeout=3)
                    except subprocess.TimeoutExpired: proc.kill()
                    raise InterruptedError("Unduhan dibatalkan.")
            if proc.returncode:
                detail = (proc.stderr.read() if proc.stderr else b"").decode("utf-8", "replace")[-1200:]
                raise RuntimeError(f"FFmpeg stream-copy merge gagal: {detail}")
            report(destination.stat().st_size, destination.stat().st_size)
            return source.filename
        finally:
            shutil.rmtree(work, ignore_errors=True)
