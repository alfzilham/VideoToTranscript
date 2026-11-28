# Video Downloader QA Record

Updated 2026-11-28. Measurements below are from actual downloads in this Windows workspace unless explicitly called a unit test. No acquisition was attempted for the unrelated Terminator URL.

## Mux reliability and shared workers — 2026-11-28

Evidence reviewed: ClipUp `runs/vtt_uat_20261127_01/uat_report.md` and `runs/vtt_uat_20261127_02/xqc_retry/recovery/recovery_manifest.json`. These files are outside this repository and were read only. The UAT report records both complete xQc tracks and a VTT mux that remained idle for over nine minutes with a zero-byte `.part`; the client then cancelled. The local recovery completed with stream copy. The supplied recovery manifest does not include its exact FFmpeg argv, so a flag-by-flag command comparison cannot be substantiated. The implementation command below is compared against the recorded recovery behavior (local tracks, lossless stream copy, Matroska result).

Root cause: the YouTube adapter previously launched FFmpeg with `stderr=PIPE`, polled the child, and only read stderr after exit. If FFmpeg filled that pipe with logs, the child blocked on write while the parent waited for exit. That lifecycle also had no mux timeout. This matches the observed idle mux/zero-byte output and is supported by the old subprocess implementation; the logs alone do not prove that a specific pipe write was the exact blocked system call.

Targeted fix: stderr now goes to a temporary file, FFmpeg stdout is consumed continuously by a progress reader (`-progress pipe:1`), verbosity/stats output is suppressed, and a configurable `VTT_YOUTUBE_MUX_TIMEOUT_SECONDS` (default 3600) bounds the operation. Cancellation terminates, waits, then kills/reaps after a 5-second grace period. The command keeps `-c copy` and explicit Matroska output; no decoder/encoder or quality conversion is introduced. Mux stage progress is derived from FFmpeg `out_time` and the known duration.

| Check | Result | Evidence |
|---|---|---|
| xQc local mux reproduction | PASS | Final adapter mux ran using the already downloaded `video_track.mp4` (471,361,559 bytes) and `audio_track.webm` (12,681,269 bytes) from the supplied recovery run; no network acquisition or external workspace writes. This 14m43s source also exercises a longer mux. Result `tmp/xqc-mux-uat/xqc-final-mux-rerun.mkv.part`, 483,776,680 bytes; mux stage reported 13 progress updates and completed. |
| xQc source properties retained | PASS | Final FFprobe: Matroska, 883.161 s, H.264 High 1920×1080 yuv420p, ~59.94 fps, plus Opus stereo 48 kHz. Matches the supplied UAT source track properties. FFmpeg uses `-map 0:v:0 -map 1:a:0 -c copy`; source tracks are not re-encoded or overwritten. |
| xQc complete decode / digest | PASS | `ffmpeg -v error -i <output> -f null NUL` exited 0 across the full 883.161-second video. Final rerun SHA-256: `fbd594435a6e975c17f2a1f343c554d599e7674b990244766a0ccd0b6fa9ee85`. Container metadata may differ from the separate recovery output; byte-identical container SHA is not expected. |
| Two-client transcription FIFO | PASS (automated API simulation) | Added regression creates requests through two independent FastAPI TestClients concurrently. Both are accepted; queue position is observable, and instrumentation confirms at most one transcription handler runs at once. This tests API concurrency and queue coordination without launching two external ClipUp/TimChao installations. |
| FIFO, queue monitoring, cancellation, worker release | PASS (automated) | Tests cover queue ordering and position, queued cancellation, active cancellation signal, terminal status, worker availability/release, and request acceptance without using 409 as normal queue control. |
| Restart recovery | PASS (automated) | Persisted queued transcription inputs resume if present; active transcription is marked `interrupted`; missing queued inputs become `error`. Persisted nonterminal downloads become `interrupted` and are not retried. |
| Full backend regression suite | PASS | `backend/.venv/Scripts/python.exe -m pytest backend/tests -q --tb=short`: **30 passed** after the current fixes. |
| Existing service restart/live API check | PASS (2026-11-28) | Reconciled all job IDs in the TimChao and ClipUp checkpoints against their status routes; all reported 404. TimChao job `52436e4e-e425-4e45-a748-5766bdba0d7e` had a temp input/audio directory dated Nov 27, before the current backend process started Nov 28; the directory was left untouched. ClipUp's latest xQc download is terminal-cancelled in its checkpoint; the validated local xQc tracks were not downloaded again. Port 8000 belonged to the project Uvicorn tree; its CPU delta was 0 over 3 seconds. The only backend restart was performed after the recorded jobs were absent and workers had no known active checkpoint. |

## Runtime deployment — 2026-11-28

The final backend is running the current workspace code on `127.0.0.1:8000` (listener PID 2552; project Python 3.11 virtual environment). It uses the standard SQLite path `C:\Users\LENOVO\.video-to-transcript\job-state.sqlite3` with no `VTT_JOB_STATE_DB` override; the database was created at 12,288 bytes. Frontend port 3000 remained active (PID 5916).

| Runtime check | Result | Evidence |
|---|---|---|
| OpenAPI | PASS | `GET /openapi.json`: HTTP 200, `Video to Transcript` 1.0.0. |
| Queue/API routes | PASS | OpenAPI contains `GET /api/jobs`, `GET /api/jobs/{job_id}`, `GET /api/worker/status`, `POST /api/jobs/{job_id}/cancel`, and `GET /api/downloader/queue`. Existing `/api/status/{job_id}` and downloader routes remain present. |
| Live queue status | PASS | `GET /api/worker/status` reported both pipelines at concurrency 1, no active job, empty queue, and `worker_available: true`; `GET /api/downloader/queue` returned the same download-worker state. After smoke cleanup, `GET /api/jobs` returned an empty list. |
| Runtime queue position and cancellation | PASS (synthetic, no media) | A synthetic queued row in the default SQLite DB was visible through the running API at queue position 1; cancellation returned `cancelled`, and status became terminal. No transcription or download was submitted. |
| Default-DB persistence across backend restart | PASS (synthetic, no media) | With both workers idle and queues empty, the backend was restarted. The same synthetic job remained `cancelled` through `GET /api/jobs/{job_id}`; the test row was then removed. This validates the runtime API against the production-default DB path without launching a heavy job. |
| Frontend smoke | PASS | `GET http://127.0.0.1:3000/downloader`: HTTP 200. No frontend files or UI/UX changed. |

The service remains running after validation. The SQLite database contains no smoke job. No xQc media was re-downloaded; no files in either Clipper workspace were modified.

Download worker API: `GET /api/downloader/queue`; combined status: `GET /api/worker/status`; transcription status/list: `GET /api/jobs`, `GET /api/jobs/{job_id}`; cancellation: `POST /api/jobs/{job_id}/cancel`. See `docs/VIDEO_DOWNLOADER_API.md` for response fields and restart semantics.

## Environment recovery

- Backend runtime: `backend/.venv`, Python 3.11.0. Root `.venv` is a separate Python 3.12 environment and is not the backend runtime.
- PyPI DNS and HTTPS access succeeded from the approved network-enabled install context. Earlier package install failures were environment DNS/network restrictions, not an invalid package name or a bad PyPI URL. No network security settings were changed.
- Installed and importable in the backend venv: Pytubefix 11.2.2, pytest 8.4.2, httpx 0.28.1, Google API Python Client 2.202.0, Google Auth OAuthlib 1.5.0, Streamlink 8.6.3.
- `vtt-activate` was invoked from the Windows PowerShell profile. Its first attempt could not launch `wt.exe` under the restricted process context; the authorized retry started both services. At validation, PID 20772 served the project Uvicorn app on 127.0.0.1:8000 and PID 23440 served the project's Next.js dev server on port 3000; both returned HTTP 200 (`/openapi.json`, `/downloader`). No unrelated process or network security setting was changed.
- The profile has a UTF-8 BOM and its existing `vtt-backend` configures Google OAuth. Persistent Twitch Client ID wiring, backup, and profile edit were not applied because the requested gate requires a successful real Clip UAT; no eligible Clip was available.
- FFmpeg and FFprobe are available on `PATH`.

## Results

| Check | Result | Evidence |
|---|---|---|
| Backend regression suite | PASS | Final run: `backend/.venv/Scripts/python.exe -m pytest backend/tests -q --tb=short`: **30 passed**. Includes API/transcription regressions, downloader URL/security/resource checks, provider parsing, blank OAuth-token defaults, HLS rendition/live guard, DASH templates, cancellation/partial cleanup, corrupt-media rejection, FIFO worker coordination, restart recovery, and concurrent-client acceptance. |
| Direct source/browser acquisition | PASS | UI inspected `https://download.samplelib.com/mp4/sample-5s.mp4`, offered one `original` rendition, and downloaded 2,848,208 bytes from the direct source. No merge was needed. |
| Direct FFprobe/full decode/SHA-256 | PASS | FFprobe: 1920×1080, 30 FPS, H.264/AAC, duration 5.758549 s, video 3,857,402 bps/audio 127,998 bps. `original_file`, re-encode No, full decode PASS. SHA-256 `05bd857af7f70bf51b6aac1144046973bf3325c9101a554bc27dc9607dbbd8f5`. Preview Range returned 206/1024 bytes; history entry present. |
| Direct preview delivery and Edge playback | PASS (endpoint playback); prior UI failure not reproduced | Live response: `206 Partial Content`, `Content-Type: video/mp4`, `Accept-Ranges: bytes`, `Content-Length: 1024`, `Content-Range: bytes 0-1023/2848208`, inline disposition. Current Edge loaded the same preview URL as native media and visibly played the 5.758549 s H.264 High, `avc1.640028`, 1920×1080, 30 FPS, yuv420p + AAC-LC MP4 through its final frame. No remux or original-file change was made. The previous page fallback did not reproduce on the current running services; native Edge media page does not expose an HTMLMediaElement `MediaError` object for this playback, so the old transient client-side error code/root cause is not recoverable. |
| Direct Send to Transcript | PASS | Browser “Send to Transcript” opened the existing transcription page; `small` completed at 100%. The sample yielded the normal “no speech recognized” result. |
| YouTube source inspection — primary source | PASS | Pytubefix inspected Blender Foundation's CC BY 3.0 Big Buck Bunny upload `https://www.youtube.com/watch?v=YE7VzlLtp-4`; 17 native formats. Selected 1920×1080 24 FPS VP9 + Opus. |
| YouTube download / quality / merge | PASS | Actual 106,523,269-byte result. Adaptive video/audio merged by FFmpeg stream-copy to Matroska; no transcode. |
| YouTube FFprobe / full decode / SHA-256 | PASS | FFprobe: 596.501 s, 1920×1080, 24 FPS, VP9/Opus. Full decode passed. Manifest SHA-256 matched file: `9d44c38a55af996e5c20981e4e38993024a99f828dd17ed76f2424a4713edb3a`. Preview returned 206; history entry present. |
| HLS quality selection / acquisition | PASS | Actual Mux Big Buck Bunny VOD manifest; selected 1920×1080, H.264 rendition, declared 6221 kbps. Result 487,257,962 bytes, FFprobe 1920×1080 60 FPS H.264/AAC, duration 634.59 s. Stream-copy mux; full decode passed; preview 206; history present. Manifest SHA-256 matched local file: `0272bd107ba70992ce832d3d0226f709629b077ae7092695848f43c2d881ec65`. |
| DASH quality selection / acquisition | PASS | Actual Akamai Big Buck Bunny static MPD: 10 video renditions; highest selected 3840×2160 30 FPS AVC, declared 14,931 kbps, with separate audio. Job `43fe57da-76e8-49c0-8ac9-146292330da5` completed via TestClient. Result 939,017,036 bytes, elapsed 344.14 s. |
| DASH FFprobe / full decode / SHA-256 | PASS | FFprobe: 634.566 s, 3840×2160 30 FPS H.264/AAC, `matroska,webm`. Full decode passed; manifest SHA-256 matched file: `ce0d94e62c0ba07dd81bbac326da406ef4f1b0800c2e41a1fc85e338b65dce39`. Preview returned 206; history entry present; no re-encoding. |
| Browser UI YouTube UAT | PASS | Rebuilt `/downloader` UI inspected the licensed source, showed 17 formats, downloaded recommended 1080p24 VP9/Opus, then displayed 1920×1080/24, VP9/Opus, `matroska,webm`, 596 s, 101.6 MB, full decode PASS, re-encode No, and SHA-256. Job `457ff8e3-8665-4c12-bec9-1269ff931195`; SHA-256 `7e783809c958422db97ca3dffe0026d13df575c57ebcadaecf6eb5774f6e2a9a`; history displayed the result. |
| Google Drive OAuth/source inspection | PASS | Local OAuth Client JSON and token were loaded without displaying credentials. Drive OAuth succeeded; 100 video candidates were listed and 100 had `canDownload=true`. An authorized video was inspected with one native `original` format, estimated 29,600,177 bytes, 3840×2160. |
| Google Drive actual acquisition/quality | PASS | Official Drive `get_media` downloaded the 29,600,177-byte original. No conversion or merge was needed. FFprobe: 3840×2160, 59.94 FPS, HEVC/AAC, video 121,734,239 bps/audio 317,377 bps, duration 1.813333 s, MP4 family. |
| Google Drive full decode/hash/preview/history | PASS | Full decode passed; SHA-256 `854f70898f7e37c5caa2ed80691cf0faf8d325fb809a3e5b494a478e65dca91f`. Range preview returned 206/1024 bytes; manifest metadata and history matched the completed job. |
| Google Drive Send to Transcript | PASS | `/api/downloader/transcribe/{job_id}` accepted the actual downloaded original. The existing Whisper `small` pipeline completed with status `done`; transcript content is not reproduced here. |
| YouTube/HLS/DASH Send to Transcript | PASS | Each previously validated real-source output was passed through `/api/downloader/transcribe/{job_id}` with the actual Whisper `small` model. All three jobs reached `done`; transcript contents are not reproduced. |
| Pytubefix vs yt-dlp benchmark | PASS (one sequential sample) | Same source tracks: format 248 (yt-dlp alias 248-sr), 1920×1080/24 VP9 plus audio 251-drc Opus. Pytubefix inspect+download+merge: 162.48 s, 106,523,269 bytes, 655,606 B/s. yt-dlp extract+download+merge: 50.59 s, 106,521,883 bytes, 2,105,733 B/s. Both FFprobe metadata match and full decode passed. Network/CDN/cache timing was not controlled; this single pair is an observed sample, not a general speed ranking. |
| TypeScript typecheck | PASS | `cd frontend; npm run typecheck` completed with `tsc --noEmit`. |
| Frontend production build | PASS | `cd frontend; npm run build`; Next.js generated `/` and `/downloader`. |
| Backend port 8000 | PASS | `vtt-activate` started the project backend; listener PID 20772 and Uvicorn command line were confirmed. OpenAPI returned HTTP 200. |
| Frontend port 3000 / browser UAT | PASS | `vtt-activate` started the project Next.js server; listener PID 23440 and its project command line were confirmed. `/downloader` returned HTTP 200; direct-source browser UAT completed. |
| Twitch authentication | PASS | Existing token refreshed without repeating OAuth; Helix `/users` returned 200. The token includes the configured Clip scope. No token or credential values are recorded. |
| Twitch target Clip download | OPTIONAL — AUTHORIZATION RESTRICTED | Helix download URL generation is available only when the token user is authorized as editor/broadcaster for that target channel; the official API returns 403 otherwise. The user's account lacks a test Clip for the targets under evaluation, so no media acquisition is claimed. This optional provider does not block Production Ready status for the supported platforms. |
| PowerShell profile Twitch integration | OPTIONAL — NOT REQUIRED | Existing profile continues to configure Google Drive. Twitch auth passed, while Clip download remains restricted per target authorization; no persistent profile change is needed for the optional provider or for startup with `vtt-activate`. |
| Google Drive overall | PASS | Official OAuth, canDownload, original media download, FFprobe/full decode/hash, Range preview/history, and actual transcript handoff passed; measurements are recorded above. |
| Whop | SKIPPED_BY_OWNER | Owner removed Whop as an active target. No Whop adapter work, research, or UAT was performed for this checkpoint. |
| HLS/DASH safeguards | PASS (offline + real HLS and DASH) | HTTP(S) public-address/redirect validation is applied per manifest and media resource. Encrypted/DRM, live/dynamic, byte-range and unsupported structures are rejected. Actual static HLS and DASH acquisitions both completed and passed full validation. |
| Security/resource regression | PASS | Automated suite exercises private/internal URL rejection, unsupported schemes, public URL validation, bounded downloader job concurrency, cancellation cleanup, corrupt media rejection and safe persistent manifests. No network security configuration was changed. |
| Production readiness gate | PASS — owner-approved scope | YouTube is the primary source; direct URL, Drive, HLS and DASH real-source UAT passed. Twitch is optional and authorization-restricted by channel role; that does not block production status. Edge played the direct preview endpoint through completion. The earlier inline-page fallback did not reproduce, so no preview code change was needed. |
| Documentation finalization | PASS | Final owner-approved platform matrix, production scope, Twitch limitation, external Clipper Agent workflow, API request/response examples, persistent storage layout, and `vtt-activate` startup steps are documented across the API, architecture, specification, workflow, QA, and README. |

YouTube is the primary production source. The source used for real UAT is the Blender Foundation's Big Buck Bunny, which its official project page identifies as Creative Commons Attribution 3.0. The original `0mr5_Jfv7NA` link resolves to a Terminator music video; it was not used for download because no source permission was established.

## Production readiness

Owner-approved release scope treats Twitch as optional. Production readiness is **PASS** for YouTube (primary), direct URL, Google Drive, HLS, and DASH. Twitch authentication is PASS; downloading a particular target remains role-restricted and is not a release blocker. Whop is `SKIPPED_BY_OWNER`.

## Adapter coverage and limits

- YouTube uses Pytubefix native streams, explicit quality choice, and FFmpeg `-c copy` mux for adaptive streams. It does not fall back to yt-dlp; the existing transcription pipeline remains separate.
- Google Drive uses the official API and original media blob; the authorized source passed acquisition, validation, and transcript handoff UAT.
- Twitch authentication passed. Clip media remains optional and restricted to channels where the token user has the official broadcaster/editor authorization; no acquisition claim is made for other channels. TwitchDownloader can technically download clips/VODs but is third-party and is not used as an authorization workaround. The official API boundary is described in the source links below.
- HLS supports complete, unencrypted VOD playlists; DASH supports static, unencrypted, single-period VOD using supported `SegmentTemplate`, `SegmentList`, or direct media `BaseURL` forms. Both acquire validated resources and stream-copy mux to Matroska. They reject DRM/encryption, live media, byte-range segments, and unsupported manifest forms.
- Streamlink 8.6.3 was installed and reviewed as an alternative acquisition engine. The implementation uses its own manifest/resource walker so every manifest, redirect, and segment uses the application's SSRF checks and pinned public-address connections; Streamlink is therefore not a runtime dependency. FFmpeg is used for lossless mux and validation, not transcoding. N_m3u8DL-RE is not used because the current supported public VOD cases do not need it and it is not part of the app's security-checked fetch path.
- Whop is `SKIPPED_BY_OWNER` for this checkpoint.

## Sources used

- Blender Big Buck Bunny license: <https://peach.blender.org/about/>
- Mux HLS test streams: <https://test-streams.mux.dev/>
- Twitch official Clips API: <https://dev.twitch.tv/docs/api/reference/clips>
- Twitch official Clips API overview: <https://dev.twitch.tv/docs/api/clips>
- Twitch official authentication scopes: <https://dev.twitch.tv/docs/authentication/scopes>
- Twitch Terms of Service: <https://www.twitch.tv/p/en/terms-of-service/>
- Third-party TwitchDownloader CLI capabilities (not an authorization source): <https://github.com/lay295/TwitchDownloader/blob/master/TwitchDownloaderCLI/README.md?plain=1>
- Google Drive official download guide: <https://developers.google.com/workspace/drive/api/guides/manage-downloads>
- Whop public API docs: <https://docs.whop.com/llms.txt>
- Whop official AI/MCP guide: <https://docs.whop.com/developer/guides/ai_and_mcp.md>
- Twitch official Device Code Grant: <https://dev.twitch.tv/docs/authentication/getting-tokens-oauth/>
- Twitch official Clips Download API and scopes: <https://dev.twitch.tv/docs/api/reference/clips>
