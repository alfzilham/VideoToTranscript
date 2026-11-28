from __future__ import annotations

import threading
import time

from backend.jobs import JobStore


def wait_for(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def payload(tmp_path, name):
    workdir = tmp_path / name
    workdir.mkdir()
    source = workdir / "source.wav"
    source.write_bytes(b"queued test source")
    return {"workdir": str(workdir), "source": str(source), "model": "small", "title": name}


def test_fifo_worker_reports_position_and_releases_after_terminal(tmp_path):
    jobs = JobStore(tmp_path / "queue.sqlite3")
    started = threading.Event()
    release = threading.Event()
    order = []

    def handler(job_id, _payload, _cancel):
        order.append(job_id)
        if len(order) == 1:
            started.set()
            assert release.wait(3)
        jobs.update(job_id, status="done", progress=100, transcript="ok", filename_suggestion="ok.txt")

    jobs.configure(handler)
    first, second = jobs.create("transcribing"), jobs.create("extracting")
    jobs.enqueue(first.id, payload(tmp_path, "one"))
    assert started.wait(2)
    jobs.enqueue(second.id, payload(tmp_path, "two"))

    snapshot = jobs.worker_status()
    assert snapshot["concurrency"] == 1
    assert snapshot["worker_available"] is False
    assert snapshot["active_job"]["job_id"] == first.id
    assert snapshot["queue"][0]["job_id"] == second.id
    assert jobs.get(second.id).queue_position == 1

    release.set()
    assert wait_for(lambda: jobs.get(second.id).status == "done")
    assert order == [first.id, second.id]
    assert jobs.worker_status()["worker_available"] is True


def test_queued_and_active_cancellation_have_explicit_terminal_status(tmp_path):
    jobs = JobStore(tmp_path / "cancel.sqlite3")
    started = threading.Event()

    def handler(job_id, _payload, cancel_event):
        started.set()
        assert cancel_event.wait(3)
        jobs.update(job_id, status="cancelled", stage="cancelled", error_message="cancelled by test")

    jobs.configure(handler)
    active, queued = jobs.create("transcribing"), jobs.create("extracting")
    jobs.enqueue(active.id, payload(tmp_path, "active"))
    assert started.wait(2)
    jobs.enqueue(queued.id, payload(tmp_path, "queued"))
    assert jobs.cancel(queued.id)
    assert jobs.get(queued.id).status == "cancelled"
    assert jobs.cancel(active.id)
    assert wait_for(lambda: jobs.get(active.id).status == "cancelled")
    assert jobs.worker_status()["worker_available"] is True


def test_restart_marks_inflight_interrupted_and_preserves_fifo_entries(tmp_path):
    database = tmp_path / "restart.sqlite3"
    original = JobStore(database)
    active = original.create("extracting")
    original.update(active.id, status="extracting", stage="extracting", progress=31)
    queued = original.create("transcribing")
    original.enqueue(queued.id, payload(tmp_path, "recoverable"))
    preparing = original.create("extracting", preparing=True)

    restarted = JobStore(database)
    assert restarted.get(active.id).status == "interrupted"
    assert restarted.get(active.id).stage == "interrupted"
    assert restarted.get(active.id).error_message == "Backend restarted before this job completed."
    assert restarted.get(queued.id).status == "queued"
    assert restarted.get(queued.id).queue_position == 1
    assert restarted.get(preparing.id).status == "error"
    assert "preparation" in restarted.get(preparing.id).error_message
