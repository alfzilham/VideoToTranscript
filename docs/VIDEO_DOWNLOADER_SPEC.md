# Video Downloader Specification

## Scope

The additive downloader page at `/downloader` acquires public, directly addressable video files. It preserves the bytes returned by the source, records a SHA-256, probes actual media properties with FFprobe, performs a full decode with FFmpeg, and stores verified media under `downloads/YYYY-MM-DD/<job-id>/` with a JSON manifest.

The transcription YouTube pipeline (`yt-dlp` audio selection) is unchanged. The downloader does not fall back to yt-dlp.

## Current source support

| Source | State | Notes |
|---|---|---|
| Public direct HTTP/HTTPS video file | Implemented | HEAD/Range inspection, streamed download, exact response bytes preserved |
| YouTube | Adapter implemented; environment blocked | Pytubefix native stream enumeration, explicit format selection and separate-track stream-copy merge. Acquisition is not verified here |
| Twitch | Conditional / unavailable | Requires an authorized official workflow; not configured |
| Whop | Conditional / unavailable | Requires owner-authorized original Content Library access; not configured |
| Google Drive | Conditional / unavailable | Drive API/OAuth and original-file capability checks are not configured |
| HLS/DASH | Recognized / unavailable | No manifest/segment adapter; DRM and access controls are not bypassed |
| Other platforms | Unsupported | Must expose a public direct video file to use the implemented adapter |

YouTube dimensions, FPS, codec and estimated size are populated from discovered native streams where Pytubefix exposes them. Unknown properties remain unavailable. For direct files, technical metadata is only known after acquisition and FFprobe validation. No artificial quality options or upscaling are offered.

## Resource defaults

- `VTT_DOWNLOAD_MAX_BYTES`: 10 GiB.
- `VTT_DOWNLOAD_MAX_CONCURRENT`: 1.
- `VTT_DOWNLOAD_INSPECTION_TTL`: 900 seconds.
- `VTT_DOWNLOAD_DIR`: project `downloads/` directory.

Completed media is retained and excluded from Git. Partial files are removed after errors and cancellation. Direct downloads use bounded timeouts and 1 MiB chunks. Public IP validation is applied to the input host and each redirect, with connections pinned to the resolved address.
