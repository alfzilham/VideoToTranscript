# Video Downloader Architecture

## Flow

`/downloader` → `/api/downloader/inspect` → source registry → direct-file, Pytubefix YouTube, authorized Twitch Clip, Google Drive API original, or static HLS/DASH VOD adapter → in-memory inspection ID (15 minute expiry).

`/api/downloader/download` validates the inspection and format ID, rechecks the source, and enqueues a job. One FIFO downloader worker writes a `.part` file, enforces configured byte and disk limits, validates media with FFprobe and a full FFmpeg decode, computes SHA-256, and atomically renames/saves a manifest. Results and job snapshots remain on disk; active cancellation state remains in memory. A nonterminal download found after restart is marked `interrupted` and is not retried.

## Modules

- `backend/downloader/security.py`: HTTP(S), port, DNS/IP, redirect, and pinned-connection checks.
- `backend/downloader/registry.py`: platform detection and adapter selection; unsupported or unconfigured providers return explanatory messages.
- `backend/downloader/adapters/base.py`: shared adapter contract.
- `backend/downloader/adapters/direct.py`: direct source inspection and streamed byte-preserving acquisition.
- `backend/downloader/adapters/youtube.py`: native Pytubefix format discovery, explicit itag selection and optional FFmpeg stream-copy mux; Pytubefix is required to inspect/download YouTube.
- `backend/downloader/adapters/twitch.py`, `backend/downloader/twitch_auth.py`: official Helix Clip inspection/download URLs and Device Code Grant authorization for an authorized editor token; token/refresh data stays in a local user-data file; no generic VOD scraping.
- `backend/downloader/adapters/google_drive.py`, `backend/downloader/google_drive_auth.py`: Drive API `canDownload` check and original blob transfer using local OAuth Desktop consent.
- `backend/downloader/adapters/hls_dash.py`: static unencrypted HLS/DASH manifest selection and per-resource validated acquisition; FFmpeg stream-copy mux to Matroska.
- `backend/downloader/jobs.py`: single FIFO worker lifecycle, persisted progress snapshots, queue positions, cancellation, restart recovery, cleanup, and final manifest creation.
- `backend/downloader/validator.py`: FFprobe metadata, FFmpeg full decode, and SHA-256.
- `backend/downloader/storage.py`: safe persistent directory/manifest access and history.
- `backend/downloader/router.py`: `/api/downloader` API and streamed file/range responses.
- `frontend/components/TopBar.tsx`, `frontend/app/downloader/page.tsx`: shared navigation and downloader UX.

The downloader and transcription job slots are separate. Sending a stored video to transcription passes its existing file path to the old pipeline and gives that pipeline a distinct temporary working directory; transcription cleanup therefore cannot remove the stored original.

Transcription from URL, upload, or a stored downloader result shares one SQLite-backed FIFO worker (`~/.video-to-transcript/job-state.sqlite3`). The worker exposes status and cancellation routes for local clients; each backend process must run with one Uvicorn worker so TimChao and ClipUp coordinate through the same queue. Queued inputs resume after restart if present, while an already active transcription is marked `interrupted` and requires a new request.

## Native fidelity

The direct adapter copies response bytes without FFmpeg rewriting. YouTube progressive streams are copied; adaptive tracks are muxed with FFmpeg `-c copy`, without transcoding. `reencoded=false` describes acquisition, and a successful decode is a technical check, not a judgment of perceived sharpness or editorial quality.

Real acquisition UAT passed for direct media, YouTube, Google Drive, HLS VOD, and DASH VOD. Google Drive used the user's local OAuth; its original 4K file passed FFprobe, full decode, hash, byte-range preview, history, and transcript handoff. Twitch is optional: authentication passes, while official Clip download URLs remain limited to users authorized as broadcaster/editor for each target channel. This authorization boundary does not block production readiness for the other supported sources. Edge plays the direct preview URL through completion with valid MP4 Range headers; the earlier inline fallback was not reproducible. Whop is `SKIPPED_BY_OWNER`. See `docs/VIDEO_DOWNLOADER_QA.md` for measured source properties, browser playback evidence and remaining readiness gates.

All HLS/DASH manifests and segments pass through public URL and redirect validation. The supported subset rejects encrypted/DRM and live sources, byte ranges, and unsupported manifest structures. The application's custom fetch path is used instead of Streamlink so each resource remains inside the SSRF protections; FFmpeg only stream-copies/remuxes and validates media.

## External Clipper Agent

A separate agent on the same workstation can use the local `/api/downloader` inspection, download, status, and result routes to receive the selected native source and verified metadata. The persistent original remains at `downloads/YYYY-MM-DD/<job_id>/<filename>` with a manifest containing FFprobe properties and SHA-256. The agent can request a transcript through `/api/downloader/transcribe/{download_id}` and poll the existing transcription status/result API. This is a local API contract, not a remote callback or an editing/rendering service; it is unauthenticated and must remain bound to loopback. See `docs/VIDEO_DOWNLOADER_API.md`.
