"""Offline tests for downloader safeguards and byte-preserving acquisition."""
from __future__ import annotations

import tempfile
import time
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.downloader.adapters.direct import DirectAdapter
from backend.downloader.jobs import DownloadJobManager
from backend.downloader.registry import detect_platform
from backend.downloader.security import UnsafeURLError, validate_public_url
from backend.downloader import storage
from backend.downloader.storage import safe_media_filename
from backend.downloader.validator import inspect_media, sha256_file, validate_full_decode


class FakeConnection:
    def close(self):
        pass


class FakeResponse:
    def __init__(self, status=200, headers=None, body=b""):
        self.status = status
        self.headers = headers or {}
        self.body = body

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def read(self, size=-1):
        if size < 0:
            value, self.body = self.body, b""
            return value
        value, self.body = self.body[:size], self.body[size:]
        return value

    def close(self):
        pass


class DownloaderCoreTests(unittest.TestCase):
    def test_blank_provider_token_paths_use_user_data_defaults(self):
        from backend.downloader.adapters.google_drive import _credentials
        from backend.downloader.adapters.twitch import TwitchAdapter

        with patch.dict("os.environ", {
            "VTT_TWITCH_TOKEN_FILE": "",
            "VTT_GOOGLE_DRIVE_TOKEN_FILE": "",
        }, clear=False):
            self.assertEqual(TwitchAdapter().token_file, Path.home() / ".video-to-transcript" / "twitch-token.json")
            with patch.dict("os.environ", {"VTT_GOOGLE_DRIVE_OAUTH_CLIENT_FILE": ""}):
                with self.assertRaisesRegex(RuntimeError, "OAUTH_CLIENT_FILE"):
                    _credentials()

    def test_google_drive_urls_extract_only_file_ids(self):
        from backend.downloader.adapters.google_drive import extract_drive_file_id

        self.assertEqual(extract_drive_file_id("https://drive.google.com/file/d/Abcdef_12345/view"), "Abcdef_12345")
        self.assertEqual(extract_drive_file_id("https://drive.google.com/open?id=Abcdef_12345"), "Abcdef_12345")
        with self.assertRaises(ValueError):
            extract_drive_file_id("https://evil.example/file/d/Abcdef_12345")

    def test_twitch_clip_slug_accepts_official_hosts_only(self):
        from backend.downloader.adapters.twitch import _clip_slug

        self.assertEqual(_clip_slug("https://clips.twitch.tv/SomeClip-123"), "SomeClip-123")
        self.assertEqual(_clip_slug("https://www.twitch.tv/channel/clip/SomeClip_123"), "SomeClip_123")
        with self.assertRaises(ValueError):
            _clip_slug("https://evilclips.twitch.tv/SomeClip-123")

    def test_hls_master_selects_highest_quality_and_rejects_live(self):
        from backend.downloader.adapters import hls_dash

        master = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360,CODECS="avc1.4d401e,mp4a.40.2"
low.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=4000000,RESOLUTION=1920x1080,FRAME-RATE=30,CODECS="avc1.640028,mp4a.40.2"
high.m3u8
"""
        with patch.object(hls_dash, "_playlist", return_value=(master.splitlines(), "https://cdn.example/master.m3u8")), \
             patch.object(hls_dash, "_media_playlist_choice", side_effect=[(["low.ts"], 5.0, ""), (["high.ts"], 5.0, "")]):
            formats, choices, duration = hls_dash._parse_hls("https://cdn.example/master.m3u8")
        self.assertEqual(formats[0].width, 1920)
        self.assertEqual(choices[formats[0].format_id].video_segments, ["high.ts"])
        self.assertEqual(duration, 5.0)
        with patch.object(hls_dash, "_playlist", return_value=(["#EXTM3U", "segment.ts"], "https://cdn.example/live.m3u8")):
            with self.assertRaisesRegex(ValueError, "Live or incomplete"):
                hls_dash._media_playlist_choice("https://cdn.example/live.m3u8")

    def test_dash_template_expands_sequence_with_init_segment(self):
        import xml.etree.ElementTree as ET
        from backend.downloader.adapters.hls_dash import _dash_rep_segments

        xml = ET.fromstring("""<MPD><Period><AdaptationSet><Representation id="v1" bandwidth="800000"><BaseURL>https://cdn.example/video/</BaseURL><SegmentTemplate initialization="init-$RepresentationID$.m4s" media="chunk-$Number%03d$-$Time$.m4s" duration="4" timescale="1" startNumber="7"/></Representation></AdaptationSet></Period></MPD>""")
        root, period, adaptation, rep = xml, xml.find("Period"), xml.find("Period/AdaptationSet"), xml.find("Period/AdaptationSet/Representation")
        root.set("_source_url", "https://cdn.example/manifest.mpd")
        urls, init, ext = _dash_rep_segments(root, period, adaptation, rep, 9)
        self.assertEqual(init, "https://cdn.example/video/init-v1.m4s")
        self.assertEqual(urls, ["https://cdn.example/video/chunk-007-0.m4s", "https://cdn.example/video/chunk-008-4.m4s", "https://cdn.example/video/chunk-009-8.m4s"])
        self.assertEqual(ext, ".mp4")

    def test_private_and_non_http_urls_are_rejected(self):
        for url in ("http://127.0.0.1/video.mp4", "http://169.254.169.254/latest/meta-data", "file:///C:/video.mp4", "https://user:secret@example.com/video.mp4"):
            with self.subTest(url=url), self.assertRaises(UnsafeURLError):
                validate_public_url(url)

    def test_windows_filename_is_safe(self):
        self.assertEqual(safe_media_filename("C:\\videos\\CON.mp4"), "video.mp4")
        self.assertEqual(safe_media_filename("../nice name?.mkv"), "nice name.mkv")

    def test_provider_detection_does_not_depend_on_network_access(self):
        self.assertEqual(detect_platform("https://www.youtube.com/watch?v=example"), "youtube")

    def test_youtube_adapter_exposes_native_formats_and_highest_quality(self):
        from backend.downloader.adapters.youtube import YouTubeAdapter

        class Stream:
            def __init__(self, itag, height, fps, video, audio, size, subtype="mp4"):
                self.itag, self.height, self.fps = itag, height, fps
                self.includes_video_track, self.includes_audio_track = video, audio
                self.filesize, self.subtype = size, subtype
                self.width = 1920 if height and height >= 1080 else 1280
                self.video_codec = "avc1" if video else None
                self.audio_codec = "mp4a" if audio else None
                self.abr = "128kbps"

        class FakeYouTube:
            def __init__(self, url):
                self.title = "Native sample"
                self.length = 24
                self.thumbnail_url = "https://i.ytimg.com/example.jpg"
                self.streams = [
                    Stream(18, 360, 30, True, True, 100),
                    Stream(137, 1080, 30, True, False, 500),
                    Stream(140, None, None, False, True, 80, "m4a"),
                    Stream(299, 1080, 60, True, False, 700),
                ]

        adapter = YouTubeAdapter()
        adapter._library = lambda: FakeYouTube
        source = adapter.inspect("https://youtu.be/example")
        self.assertEqual(source.formats[0].format_id, "yt:299")
        self.assertEqual(source.formats[0].fps, 60)
        self.assertEqual(source.formats[0].container, "mkv")
        self.assertEqual(source.formats[-1].format_id, "yt:18")
        self.assertEqual(detect_platform("https://drive.google.com/uc?id=example"), "google_drive")
        self.assertEqual(detect_platform("https://stream.example/video.m3u8"), "hls_dash")

    def test_direct_inspection_does_not_invent_media_metadata(self):
        response = FakeResponse(headers={"Content-Type": "video/mp4", "Content-Length": "14", "Content-Disposition": 'attachment; filename="sample.mp4"'})
        with patch("backend.downloader.adapters.direct.open_public_response", return_value=(FakeConnection(), response, "https://public.example/sample.mp4")):
            inspected = DirectAdapter().inspect("https://public.example/sample.mp4")
        self.assertTrue(inspected.download_available)
        self.assertEqual(inspected.size_bytes, 14)
        self.assertIsNone(inspected.duration_seconds)
        self.assertIsNone(inspected.formats[0].width)
        self.assertIsNone(inspected.formats[0].fps)

    def test_direct_inspection_keeps_unknown_title_and_container_null(self):
        response = FakeResponse(headers={"Content-Type": "video/mp4", "Content-Length": "14"})
        with patch("backend.downloader.adapters.direct.open_public_response", return_value=(FakeConnection(), response, "https://public.example/")):
            inspected = DirectAdapter().inspect("https://public.example/")
        self.assertIsNone(inspected.title)
        self.assertIsNone(inspected.formats[0].container)

    def test_direct_download_preserves_exact_response_bytes(self):
        original = bytes(range(256)) * 13
        response = FakeResponse(headers={"Content-Length": str(len(original))}, body=original)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "original.mp4.part"
            progress = []
            with patch("backend.downloader.adapters.direct.open_public_response", return_value=(FakeConnection(), response, "https://public.example/original.mp4")):
                DirectAdapter().download(type("Source", (), {"url": "https://public.example/original.mp4", "filename": "original.mp4", "size_bytes": len(original)})(), target, lambda got, total: progress.append((got, total)), threading.Event())
            self.assertEqual(target.read_bytes(), original)
            self.assertEqual(progress[-1], (len(original), len(original)))

    def test_ffprobe_and_full_decode_report_actual_fixture_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "fixture.mp4"
            import subprocess
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                "-i", "color=c=black:s=32x24:r=2:d=1", "-an", "-c:v", "mpeg4", str(fixture),
            ], check=True, capture_output=True, timeout=20)
            metadata = inspect_media(fixture)
            validate_full_decode(fixture)
            size = fixture.stat().st_size
        self.assertEqual((metadata["width"], metadata["height"]), (32, 24))
        self.assertEqual(metadata["video_codec"], "mpeg4")
        self.assertEqual(metadata["file_size_bytes"], size)

    def test_download_job_persists_verified_media_and_manifest(self):
        import subprocess
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "downloads"
            fixture = Path(temporary) / "fixture.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                "-i", "color=c=black:s=32x24:r=2:d=1", "-an", "-c:v", "mpeg4", str(fixture),
            ], check=True, capture_output=True, timeout=20)
            original = fixture.read_bytes()

            class FixtureAdapter:
                def download(self, source, destination, report, cancel_event):
                    destination.write_bytes(original)
                    report(len(original), len(original))

            manager = DownloadJobManager()
            with patch.object(storage, "ROOT", root):
                job = manager.create_and_start({"size_bytes": len(original), "platform": "direct", "source": object(), "title": "Fixture", "filename": "fixture.mp4"}, FixtureAdapter(), "original")
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline and job.status not in {"done", "error", "cancelled"}:
                    time.sleep(0.05)
                self.assertEqual(job.status, "done", job.error_message)
                manifest = storage.read_manifest(job.job_id)
                self.assertIsNotNone(manifest)
                saved = Path(manifest["_directory"]) / manifest["relative_path"]
                self.assertEqual(saved.read_bytes(), original)
                self.assertEqual(manifest["sha256"], sha256_file(saved))
                self.assertTrue(manifest["full_decode_passed"])

    def test_cancel_cleans_partial_job_and_releases_worker_slot(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(storage, "ROOT", Path(temporary) / "downloads"):
                manager = DownloadJobManager()

                class WaitingAdapter:
                    def download(self, source, destination, report, cancel_event):
                        destination.write_bytes(b"partial")
                        while not cancel_event.wait(0.01):
                            pass
                        raise InterruptedError("Unduhan dibatalkan.")

                job = manager.create_and_start({"size_bytes": None, "platform": "direct", "source": object(), "title": "Cancel", "filename": "cancel.mp4"}, WaitingAdapter(), "original")
                self.assertTrue(manager.cancel(job.job_id))
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline and job.status not in {"done", "error", "cancelled"}:
                    time.sleep(0.02)
                self.assertEqual(job.status, "cancelled")
                self.assertNotIn(job.job_id, manager.active)

    def test_corrupt_download_is_rejected_and_partial_is_removed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "downloads"
            with patch.object(storage, "ROOT", root):
                manager = DownloadJobManager()

                class CorruptAdapter:
                    def download(self, source, destination, report, cancel_event):
                        destination.write_bytes(b"not a video")
                        report(11, 11)

                job = manager.create_and_start({"size_bytes": None, "platform": "direct", "source": object(), "title": "Corrupt", "filename": "corrupt.mp4"}, CorruptAdapter(), "original")
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline and job.status not in {"done", "error", "cancelled"}:
                    time.sleep(0.02)
                self.assertEqual(job.status, "error")
                self.assertEqual(job.error_code, "VALIDATION_FAILED")
                self.assertIsNone(storage.read_manifest(job.job_id))
                self.assertNotIn(job.job_id, manager.active)


if __name__ == "__main__":
    unittest.main()
