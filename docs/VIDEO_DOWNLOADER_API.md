# Video Downloader API

Base URL: `http://127.0.0.1:8000`; base path: `/api/downloader`. This is a local, single-user API with no authentication. Keep it bound to localhost and do not expose it to a LAN or public network.

## Inspect a source

```http
POST /api/downloader/inspect
Content-Type: application/json

{"url":"https://download.samplelib.com/mp4/sample-5s.mp4"}
```

Example response (IDs, metadata, and format counts are source-specific):

```json
{
  "inspection_id": "<uuid>",
  "platform": "direct",
  "title": null,
  "duration_seconds": null,
  "thumbnail_url": null,
  "download_available": true,
  "formats": [
    {"format_id":"original","label":"Original file","width":null,"height":null,"fps":null,"video_codec":null,"audio_codec":null,"container":null,"estimated_size_bytes":2848208,"native_original":true}
  ],
  "recommended_format_id": "original",
  "message": null
}
```

Use the returned `recommended_format_id` or another returned `formats[].format_id`; format IDs belong to that inspection and expire after `VTT_DOWNLOAD_INSPECTION_TTL` (default 900 seconds).

## Start and poll a download

```http
POST /api/downloader/download
Content-Type: application/json

{"inspection_id":"<uuid-from-inspect>","format_id":"original"}
```

Returns HTTP 202, e.g. `{"job_id":"<uuid>","status":"queued"}`. Jobs enter a FIFO queue; one download worker runs at a time. Poll:

```http
GET /api/downloader/status/<job_id>
```

Example status: `{"job_id":"<uuid>","status":"downloading","progress":42,"downloaded_bytes":1200000,"total_bytes":2848208,"speed_bytes_per_second":400000,"eta_seconds":5,"error_code":null,"error_message":null,"stage":"downloading","queue_position":0,"worker_available":false,"updated_at":1795852800.0}`. Status values include `queued`, `downloading`, `muxing`, `validating`, `done`, `error`, `cancelled`, and `interrupted`. `stage_progress` carries mux progress (0–99) while `progress` reports acquisition progress; `queue_position` is `0` for the active job, `1..N` for queued jobs, and null for terminal jobs. Acquisition progress can be null when the source has no known total size. `GET /api/downloader/queue` reports `pipeline`, fixed `concurrency: 1`, `worker_available`, `active_job`, `queue`, and `queue_length` without requiring clients to resubmit work.

When status is `done`, request:

```http
GET /api/downloader/result/<job_id>
```

Example result (property values vary by source):

```json
{
  "job_id":"<uuid>","filename":"sample-5s.mp4","title":null,"platform":"direct",
  "file_size_bytes":2848208,"duration_seconds":5.758549,"width":1920,"height":1080,
  "fps":30.0,"video_codec":"h264","audio_codec":"aac","video_bitrate_bps":3857402,
  "audio_bitrate_bps":127998,"container":"mov,mp4,m4a,3gp,3g2,mj2",
  "acquisition_method":"original_file","reencoded":false,"full_decode_passed":true,
  "sha256":"<64-hex-digest>","file_url":"/api/downloader/file/<uuid>",
  "preview_url":"/api/downloader/preview/<uuid>","status":"done",
  "completed_at":"<ISO-8601 timestamp>","relative_path":"sample-5s.mp4","manifest_schema":1
}
```

`GET /api/downloader/file/{job_id}` streams the verified original as an attachment. `GET /api/downloader/preview/{job_id}` serves it inline and supports one byte range (`206`, `Content-Range`, `Accept-Ranges`). `GET /api/downloader/metadata/{job_id}` returns the manifest without private filesystem paths. `GET /api/downloader/history` lists completed results. `POST /api/downloader/cancel/{job_id}` cancels queued jobs immediately or requests cancellation of active acquisition/validation, then cleans partial files. The response reports the observed `cancelled` or `cancelling` state. A restart marks a nonterminal persisted download `interrupted`; it is not silently restarted.

## Shared transcription queue

The legacy transcription routes remain available and now enqueue instead of rejecting a second request:

```http
POST /api/process/url
Content-Type: application/json

{"url":"https://www.youtube.com/watch?v=<id>","model":"small"}
```

```json
{"job_id":"<uuid>"}
```

`POST /api/process/upload` and `POST /api/downloader/transcribe/{download_id}` use the same FIFO transcription worker and retain their prior response shapes. Use `GET /api/status/{job_id}` or `GET /api/jobs/{job_id}` for status. The compatible status response contains `job_id`, `status`, `progress`, `error_message`, and adds `pipeline`, `stage`, `queue_position`, `worker_available`, and `updated_at`. States are `queued`, `downloading`, `extracting`, `transcribing`, `cancelling`, `done`, `error`, `cancelled`, and `interrupted`; queue position is zero for active and one-based for queued jobs.

- `GET /api/jobs` lists jobs without resubmission.
- `GET /api/worker/status` reports both transcription and download worker availability, active job, FIFO queue, and queue length. Each pipeline has fixed concurrency one.
- `POST /api/jobs/{job_id}/cancel` cancels queued work immediately or signals the active job to stop at a safe stage boundary. Active FFmpeg/yt-dlp/extraction subprocesses are terminated and reaped; transcript progress cancellation is cooperative. A terminal `done`, `error`, `cancelled`, or `interrupted` state is explicit.
- Transcription job state and queued inputs are stored in `~/.video-to-transcript/job-state.sqlite3` (override with `VTT_JOB_STATE_DB`). Completed transcript results are persisted there. A queued job resumes after backend restart when its input still exists. A job that had already started is marked `interrupted` because model inference cannot safely resume at its previous point; missing queued input is marked `error`.
- Download job snapshots are stored under `downloads/.jobs/`; an interrupted download is reported as `interrupted` and partial acquisition is not resumed.

This queue prevents concurrent heavy transcriptions within one backend process and gives TimChao/ClipUp read-only queue visibility. It is local coordination, not a multi-host distributed lock. Run one backend process (`--workers 1`) so both clients share the same worker state.

Both Clipper Agents should point at the same `http://127.0.0.1:8000` instance. Each agent submits its operation once, saves the returned `job_id`, and polls the status/queue endpoints; a busy worker is represented by `queued` plus `queue_position`, so the client must not retry the submit request to discover availability. Check `/api/worker/status` before or after submission for both pipeline snapshots:

```json
{
  "transcription": {
    "pipeline": "transcription", "concurrency": 1, "worker_available": false,
    "active_job": {"job_id": "<active-uuid>", "status": "transcribing", "stage": "transcribing", "progress": 72, "queue_position": 0},
    "queue": [{"job_id": "<queued-uuid>", "status": "queued", "stage": "extracting", "progress": 0, "queue_position": 1}],
    "queue_length": 1
  },
  "download": {
    "pipeline": "download", "concurrency": 1, "worker_available": true,
    "active_job": null, "queue": [], "queue_length": 0
  }
}
```

Transcription requests retain their previous contract: `POST /api/process/url` accepts `{"url":"https://youtu.be/<id>","model":"small"}`; `POST /api/process/upload` accepts multipart `file` and `model`; `POST /api/downloader/transcribe/{download_id}` accepts `{"model":"small"}`. Each returns `job_id`. Poll `GET /api/status/{job_id}` for backward compatibility or `GET /api/jobs/{job_id}` for the detailed record. Downloads use the existing inspect → download → poll status/result flow; `GET /api/downloader/queue` reports the download worker. After a backend restart, poll the saved job ID: active work is explicitly `interrupted`, queued work may resume, and terminal history remains available from SQLite.

## Send a result to VTT transcription

```http
POST /api/downloader/transcribe/<download_id>
Content-Type: application/json

{"model":"small"}
```

Returns HTTP 202 and `{"job_id":"<transcription-job-uuid>"}`. Poll `GET /api/status/{job_id}` and read `GET /api/result/{job_id}` when complete. The stored downloader original is retained.

## Errors

FastAPI error responses use `{"detail":"..."}` and include `X-Error-Code`. Inspection errors include `INVALID_URL`, `UNSUPPORTED_PLATFORM`, `SOURCE_UNAVAILABLE`, `DOWNLOAD_NOT_AVAILABLE`, `INSPECTION_EXPIRED`, and `QUALITY_UNAVAILABLE`. Job errors include `JOB_NOT_FOUND`, `FILE_TOO_LARGE`, `INSUFFICIENT_DISK_SPACE`, `DOWNLOAD_FAILED`, `VALIDATION_FAILED`, and `CANCELLED`. New jobs are queued instead of returning `JOB_BUSY`; HTTP 409 remains for a result that is not ready or cancellation of a terminal job. HTTP 404 indicates unknown/expired IDs.

## External Clipper Agent integration

An external clipper/agent running on the same computer can use the inspect → download → poll → result flow above, then read `file_url` or copy the persistent file identified by `relative_path`. The API returns source video and verified metadata; after the agent produces a clip, it may submit a transcript request using the downloaded `job_id`. VTT does not define a separate callback, remote agent protocol, or clip-editing API. A remote agent cannot reach this loopback-only service; do not solve that by exposing the unauthenticated API to the network.

## Provider boundaries

YouTube uses Pytubefix native format discovery and stream-copy mux for adaptive tracks. Google Drive uses official OAuth and retrieves the original blob only when `canDownload` allows it. HLS/DASH supports public, unencrypted VOD forms listed in the support matrix. Twitch Clip download URLs require the signed-in user to be an authorized broadcaster/editor for the target; authentication alone is not sufficient. Twitch is optional and does not block production status. Whop is `SKIPPED_BY_OWNER`.

See `docs/VIDEO_DOWNLOADER_SPEC.md` for the final support matrix and `docs/VIDEO_DOWNLOADER_QA.md` for actual test evidence.
