# Video Downloader API

Base path: `/api/downloader`. Errors keep FastAPI's compatible string `detail` and include a machine-readable `X-Error-Code` header.

## Routes

- `POST /inspect` `{ "url": "https://.../video.mp4" }` → platform and discovered formats. YouTube returns native Pytubefix stream options (itag-backed IDs, resolution/FPS/codec/container and estimated size where available); direct-source values not known before download are `null`; private URL/signature data is not returned.
- `POST /download` `{ "inspection_id": "uuid", "format_id": "original" }` → `202 {"job_id":"uuid","status":"queued"}`.
- `GET /status/{job_id}` → status, observed bytes, total, speed, ETA, progress and error.
- `GET /result/{job_id}` → actual probed properties, acquisition method, re-encode indicator, decode result, hash and file/preview URLs. `409` while processing.
- `GET /file/{job_id}` → streamed attachment.
- `GET /preview/{job_id}` → inline media with single byte-range support.
- `GET /metadata/{job_id}` → verified manifest as JSON for UI download.
- `POST /cancel/{job_id}` → request cancellation and partial-file cleanup.
- `GET /history` → completed manifests.
- `POST /transcribe/{download_id}` `{ "model": "small" }` → existing transcription `job_id`; existing `/api/status/{job_id}` and `/api/result/{job_id}` remain the status/result APIs.

## Error codes

URL/inspection errors: `INVALID_URL`, `UNSUPPORTED_PLATFORM`, `SOURCE_UNAVAILABLE`, `DOWNLOAD_NOT_AVAILABLE`, `INSPECTION_EXPIRED`, `QUALITY_UNAVAILABLE`. Job errors: `JOB_NOT_FOUND`, `JOB_BUSY`, `FILE_TOO_LARGE`, `INSUFFICIENT_DISK_SPACE`, `DOWNLOAD_FAILED`, `VALIDATION_FAILED`, `CANCELLED`.

Direct files offer one `original` option. YouTube format IDs are inspection-scoped and refreshed before acquisition; adaptive tracks are stream-copy muxed to MKV. IDs outside the inspection are rejected. YouTube requires the Pytubefix dependency in `backend/requirements.txt`.
