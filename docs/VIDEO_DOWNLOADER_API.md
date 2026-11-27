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

Returns HTTP 202, e.g. `{"job_id":"<uuid>","status":"queued"}`. Poll:

```http
GET /api/downloader/status/<job_id>
```

Example status: `{"job_id":"<uuid>","status":"downloading","progress":42,"downloaded_bytes":1200000,"total_bytes":2848208,"speed_bytes_per_second":400000,"eta_seconds":5,"error_code":null,"error_message":null}`. Status values include `queued`, `downloading`, `validating`, `done`, `error`, and `cancelled`. Progress can be null when the source has no known total size.

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

`GET /api/downloader/file/{job_id}` streams the verified original as an attachment. `GET /api/downloader/preview/{job_id}` serves it inline and supports one byte range (`206`, `Content-Range`, `Accept-Ranges`). `GET /api/downloader/metadata/{job_id}` returns the manifest without private filesystem paths. `GET /api/downloader/history` lists completed results. `POST /api/downloader/cancel/{job_id}` requests cancellation and partial-file cleanup.

## Send a result to VTT transcription

```http
POST /api/downloader/transcribe/<download_id>
Content-Type: application/json

{"model":"small"}
```

Returns HTTP 202 and `{"job_id":"<transcription-job-uuid>"}`. Poll `GET /api/status/{job_id}` and read `GET /api/result/{job_id}` when complete. The stored downloader original is retained.

## Errors

FastAPI error responses use `{"detail":"..."}` and include `X-Error-Code`. Inspection errors include `INVALID_URL`, `UNSUPPORTED_PLATFORM`, `SOURCE_UNAVAILABLE`, `DOWNLOAD_NOT_AVAILABLE`, `INSPECTION_EXPIRED`, and `QUALITY_UNAVAILABLE`. Job errors include `JOB_NOT_FOUND`, `JOB_BUSY`, `FILE_TOO_LARGE`, `INSUFFICIENT_DISK_SPACE`, `DOWNLOAD_FAILED`, `VALIDATION_FAILED`, and `CANCELLED`. HTTP 409 indicates an active/conflicting job or a result not ready; HTTP 404 indicates unknown/expired IDs.

## External Clipper Agent integration

An external clipper/agent running on the same computer can use the inspect → download → poll → result flow above, then read `file_url` or copy the persistent file identified by `relative_path`. The API returns source video and verified metadata; after the agent produces a clip, it may submit a transcript request using the downloaded `job_id`. VTT does not define a separate callback, remote agent protocol, or clip-editing API. A remote agent cannot reach this loopback-only service; do not solve that by exposing the unauthenticated API to the network.

## Provider boundaries

YouTube uses Pytubefix native format discovery and stream-copy mux for adaptive tracks. Google Drive uses official OAuth and retrieves the original blob only when `canDownload` allows it. HLS/DASH supports public, unencrypted VOD forms listed in the support matrix. Twitch Clip download URLs require the signed-in user to be an authorized broadcaster/editor for the target; authentication alone is not sufficient. Twitch is optional and does not block production status. Whop is `SKIPPED_BY_OWNER`.

See `docs/VIDEO_DOWNLOADER_SPEC.md` for the final support matrix and `docs/VIDEO_DOWNLOADER_QA.md` for actual test evidence.
