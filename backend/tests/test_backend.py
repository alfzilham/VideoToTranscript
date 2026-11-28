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


def test_fifo_job_store_accepts_a_second_queued_job(tmp_path) -> None:
    jobs = JobStore(tmp_path / "jobs.sqlite3")
    one = jobs.create("extracting")
    two = jobs.create("downloading")
    assert one.status == two.status == "queued"
    assert jobs.get(one.id).queue_position == 1
    assert jobs.get(two.id).queue_position == 2
    jobs.update(one.id, status="done", progress=100, transcript="text", filename_suggestion="a.txt")
    assert jobs.get(one.id).status == "done"
    assert jobs.get(two.id).queue_position == 1
    assert jobs.create("extracting").id not in {one.id, two.id}


def test_api_validation_and_not_found() -> None:
    assert client.post("/api/process/url", json={"url": "http://example.com/a"}).status_code == 422
    assert client.post("/api/process/url", json={"url": "https://youtu.be/a", "model": "large"}).status_code == 422
    assert client.post("/api/process/upload", files={"file": ("bad.exe", b"hello")}).status_code == 415
    assert client.get("/api/status/no-such-job").status_code == 404
    assert client.get("/api/result/no-such-job").status_code == 404


def test_upload_pipeline_mock(tmp_path, monkeypatch) -> None:
    """Run a real API upload and worker with media stages mocked (no network/model)."""
    from backend import main

    def fake_extractor(source, destination, cancel_event=None):
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
    status = client.get(f"/api/status/{job_id}").json()
    assert status["status"] == "done", status
    assert status["progress"] == 100 and status["error_message"] is None
    assert status["job_id"] == job_id and status["stage"] == "done"
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

    def fake_downloader(url, destination, max_bytes, callback, cancel_event=None):
        assert "youtu.be" in url
        source = destination / "source.webm"
        source.write_bytes(b"youtube media")
        observed.append(destination)
        callback(29)
        return source, "Talk: Introduction"

    def fake_extractor(source, destination, cancel_event=None):
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


def test_two_api_clients_are_accepted_and_processed_fifo(monkeypatch):
    """Two simultaneous ClipUp-style clients queue without 409 and share one Whisper worker."""
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor
    from backend import main

    first_started = threading.Event()
    release_first = threading.Event()
    counter_lock = threading.Lock()
    active = 0
    peak = 0
    calls = 0

    def fake_transcriber(_source, _model, callback):
        nonlocal active, peak, calls
        with counter_lock:
            active += 1
            calls += 1
            peak = max(peak, active)
            call = calls
        if call == 1:
            first_started.set()
            assert release_first.wait(3)
        callback(97)
        with counter_lock:
            active -= 1
        return [{"start": call, "end": call + 1, "text": f"job {call}"}]

    monkeypatch.setattr(main, "transcribe", fake_transcriber)
    first_client, second_client = TestClient(app), TestClient(app)
    with first_client, second_client:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first_future = pool.submit(first_client.post, "/api/process/upload", files={"file": ("one.wav", b"one", "audio/wav")})
            first_response = first_future.result(timeout=3)
            assert first_response.status_code == 202
            first_id = first_response.json()["job_id"]
            assert first_started.wait(2)

            second_future = pool.submit(second_client.post, "/api/process/upload", files={"file": ("two.wav", b"two", "audio/wav")})
            second_response = second_future.result(timeout=3)
            assert second_response.status_code == 202
            second_id = second_response.json()["job_id"]
            second_status = first_client.get(f"/api/status/{second_id}").json()
            assert second_status["status"] == "queued"
            assert second_status["queue_position"] == 1
            assert second_status["stage"] == "extracting"
            worker = first_client.get("/api/worker/status").json()["transcription"]
            assert worker["active_job"]["job_id"] == first_id
            assert worker["queue"][0]["job_id"] == second_id

            release_first.set()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and (store.get(first_id).status != "done" or store.get(second_id).status != "done"):
                time.sleep(0.01)
            assert store.get(first_id).status == store.get(second_id).status == "done"
            assert peak == 1
