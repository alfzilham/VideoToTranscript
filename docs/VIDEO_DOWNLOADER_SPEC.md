# Video Downloader Specification

## Scope

The additive downloader page at `/downloader` acquires media through supported direct and authorized source adapters. It preserves source streams (or stream-copies muxed tracks), records SHA-256, probes actual media properties with FFprobe, performs a full decode with FFmpeg, and stores verified media under `downloads/YYYY-MM-DD/<job-id>/` with a JSON manifest.

The transcription YouTube pipeline (`yt-dlp` audio selection) is unchanged. The downloader does not fall back to yt-dlp.

## Current source support

| Source | State | Notes |
|---|---|---|
| Public direct HTTP/HTTPS video file | PASS | Actual sample acquisition preserved source bytes. FFprobe/full decode/hash/history/transcript handoff passed. Preview response advertises `video/mp4` with correct byte ranges; current Edge visibly played the 5.76 s H.264/AAC source to completion. Prior inline fallback was not reproduced; see QA for limitation. |
| YouTube | PASS — Primary Source | Pytubefix inspected 17 native formats, selected 1080p24 VP9/Opus and losslessly merged adaptive tracks; browser download UAT also passed |
| Twitch Clips | OPTIONAL — Authentication PASS; download authorization-restricted | Official Helix download endpoint requires the token user to be an authorized broadcaster/editor for the target; unauthorized target requests are denied. No third-party scraping fallback. Twitch does not block production use of the other supported platforms. |
| Whop | SKIPPED_BY_OWNER | Owner withdrew Whop as an active implementation target; no adapter work or additional research is in scope |
| Google Drive | PASS | Official Drive OAuth, `canDownload`, original file acquisition, 4K native metadata and end-to-end transcript handoff passed |
| HLS VOD | PASS | Complete static VOD only; DRM/encrypted, dynamic/live, byte-range and unsupported manifest forms are rejected |
| DASH VOD | PASS | Static, supported unencrypted VOD only; DRM/encrypted, dynamic/live, byte-range and unsupported manifest forms are rejected |
| Other platforms | Unsupported | Must expose a public direct video file to use the implemented adapter |

YouTube dimensions, FPS, codec and estimated size are populated from discovered native streams where Pytubefix exposes them. Unknown properties remain unavailable. For direct files, technical metadata is only known after acquisition and FFprobe validation. No artificial quality options or upscaling are offered.

Production readiness: **PASS** for the supported downloader and transcription workflows. Twitch Clips are optional and remain subject to per-channel authorization. Edge played the tested direct MP4 preview to completion; the previously reported inline fallback was not reproduced (see QA).

## Resource defaults

- `VTT_DOWNLOAD_MAX_BYTES`: 10 GiB.
- `VTT_DOWNLOAD_MAX_CONCURRENT`: 1.
- `VTT_DOWNLOAD_INSPECTION_TTL`: 900 seconds.
- `VTT_DOWNLOAD_DIR`: project `downloads/` directory.

Completed media is retained and excluded from Git. Partial files are removed after errors and cancellation. Direct downloads use bounded timeouts and 1 MiB chunks. Public IP validation is applied to the input host and each redirect, with connections pinned to the resolved address.
