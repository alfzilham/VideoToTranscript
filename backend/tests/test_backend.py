"""Fast, offline smoke tests; actual Whisper downloads are not required."""
import asyncio
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.jobs import JobStore, safe_filename, store
from backend.main import app, run_job, validate_youtube_url
from backend.pipeline.formatter import format_segments, format_timestamp

client = TestClient(app)


def test_youtube_url_allowlist() -> None:
    assert validate_youtube_url("https://www.youtube.com/watch?v=abc")
    assert validate_youtube_url("https://youtu.be/abc")
    assert not validate_youtube_url("https://youtube.com.evil.example/watch?v=a")
    assert not validate_youtube_url("file:///etc/passwd")
    assert not validate_youtube_url("https://attacker@youtube.com:9999/a")
    assert not validate_youtube_url("https://youtu.be/")


def test_formatter() -> None:
    assert format_timestamp(3661.99) == "01:01:01"
    assert format_timestamp(-1) == "00:00:00"
    segs = [SimpleNamespace(start=2.6, text=" Hello "), SimpleNamespace(start=9, text=" world ")]
    assert format_segments(segs) == "[00:00:02] Hello\n[00:00:09] world"
    assert safe_filename("C:\\folder\\my<video>?.MP4") == "myvideo.txt"


def test_single_active_job() -> None:
    jobs = JobStore()
    one = jobs.create("extracting")
    try:
        jobs.create("downloading")
        assert False, "Must reject a second active job"
    except RuntimeError:
        pass
    jobs.update(one.id, status="done", progress=100, transcript="text", filename_suggestion="a.txt")
    assert jobs.get(one.id).status == "done"
    assert jobs.create("extracting").id != one.id


def test_api_validation_and_not_found() -> None:
    assert client.post("/api/process/url", json={"url": "http://example.com/a"}).status_code == 422
    assert client.post("/api/process/url", json={"url": "https://youtu.be/a", "model": "large"}).status_code == 422
    assert client.post("/api/process/upload", files={"file": ("bad.exe", b"hello")}).status_code == 415
    assert client.get("/api/status/no-such-job").status_code == 404
    assert client.get("/api/result/no-such-job").status_code == 404


def test_upload_pipeline_mock(tmp_path, monkeypatch) -> None:
    """Run a real API upload and worker with media stages mocked (no network/model)."""
    from backend import main

    def fake_extractor(source, destination):
        destination.write_bytes(b"mock WAV")
        return destination

    def fake_transcriber(source, model, callback):
        assert model == "small"
        callback(97)
        return [{"start": 2.0, "end": 4.0, "text": "halo dunia"}]

    monkeypatch.setattr(main, "extract_audio", fake_extractor)
    monkeypatch.setattr(main, "transcribe", fake_transcriber)
    # Execute the threaded pipeline deterministically inside this test.
    def synchronous_worker(job_id, workdir, source, url, model, title):
        run_job(job_id, workdir, source, url, model, title)

    monkeypatch.setattr(main, "start_worker", synchronous_worker)
    response = client.post("/api/process/upload", files={"file": ("rekaman.mp4", b"fake video content", "video/mp4")})
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    assert client.get(f"/api/status/{job_id}").json() == {
        "status": "done", "progress": 100, "error_message": None
    }
    assert client.get(f"/api/result/{job_id}").json() == {
        "transcript": "[00:00:02] halo dunia", "filename_suggestion": "rekaman.txt"
    }
    assert store.active_id is None


def test_upload_too_large(monkeypatch) -> None:
    from backend import main
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 2)
    resp = client.post("/api/process/upload", files={"file": ("a.mp3", b"long audio", "audio/mpeg")})
    assert resp.status_code == 413
    assert store.active_id is None


def test_youtube_pipeline_mock_and_cleanup(monkeypatch) -> None:
    """Exercise URL -> download -> ffmpeg -> Whisper -> result without network."""
    from backend import main

    observed: list[Path] = []

    def fake_downloader(url, destination, max_bytes, callback):
        assert "youtu.be" in url
        source = destination / "source.webm"
        source.write_bytes(b"youtube media")
        observed.append(destination)
        callback(29)
        return source, "Talk: Introduction"

    def fake_extractor(source, destination):
        assert source.suffix == ".webm"
        destination.write_bytes(b"converted wav")
        return destination

    def fake_transcriber(source, model, callback):
        assert source.name == "audio.wav"
        callback(90)
        return [{"start": 61, "end": 63, "text": " testing pipeline "}]

    monkeypatch.setattr(main, "download_youtube_audio", fake_downloader)
    monkeypatch.setattr(main, "extract_audio", fake_extractor)
    monkeypatch.setattr(main, "transcribe", fake_transcriber)
    monkeypatch.setattr(main, "start_worker", lambda *args: run_job(*args))

    response = client.post("/api/process/url", json={"url": "https://youtu.be/test", "model": "medium"})
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    assert client.get(f"/api/result/{job_id}").json() == {
        "transcript": "[00:01:01] testing pipeline",
        "filename_suggestion": "Talk Introduction.txt",
    }
    assert client.get(f"/api/status/{job_id}").json()["progress"] == 100
    assert observed and not observed[0].exists()


def test_pipeline_error_releases_slot(monkeypatch) -> None:
    from backend import main

    observed: list[Path] = []

    def failing_transcriber(source, model, callback):
        observed.append(source.parent)
        raise RuntimeError("Simulated Whisper failure")

    monkeypatch.setattr(main, "transcribe", failing_transcriber)
    monkeypatch.setattr(main, "start_worker", lambda *args: run_job(*args))
    response = client.post("/api/process/upload", files={"file": ("test.wav", b"mock", "audio/wav")})
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    assert client.get(f"/api/status/{job_id}").json()["status"] == "error"
    assert "Simulated Whisper failure" in client.get(f"/api/status/{job_id}").json()["error_message"]
    assert client.get(f"/api/result/{job_id}").status_code == 409
    assert store.active_id is None
    assert observed and not observed[0].exists()
