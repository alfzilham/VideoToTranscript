# Video Downloader Architecture

## Flow

`/downloader` → `/api/downloader/inspect` → source registry → direct-file or Pytubefix YouTube adapter → in-memory inspection ID (15 minute expiry).

`/api/downloader/download` validates the inspection and format ID, rechecks the source, and creates one worker. The worker writes a `.part` file, enforces configured byte and disk limits, validates media with FFprobe and a full FFmpeg decode, computes SHA-256, and atomically renames/saves a manifest. Results remain on disk; transient progress and cancellation state remain in memory.

## Modules

- `backend/downloader/security.py`: HTTP(S), port, DNS/IP, redirect, and pinned-connection checks.
- `backend/downloader/registry.py`: platform detection and adapter selection; explicitly unavailable providers return explanatory messages.
- `backend/downloader/adapters/base.py`: shared adapter contract.
- `backend/downloader/adapters/direct.py`: direct source inspection and streamed byte-preserving acquisition.
- `backend/downloader/adapters/youtube.py`: native Pytubefix format discovery, explicit itag selection and optional FFmpeg stream-copy mux; Pytubefix is required to inspect/download YouTube.
- `backend/downloader/jobs.py`: bounded worker lifecycle, progress, cancellation, cleanup, and final manifest creation.
- `backend/downloader/validator.py`: FFprobe metadata, FFmpeg full decode, and SHA-256.
- `backend/downloader/storage.py`: safe persistent directory/manifest access and history.
- `backend/downloader/router.py`: `/api/downloader` API and streamed file/range responses.
- `frontend/components/TopBar.tsx`, `frontend/app/downloader/page.tsx`: shared navigation and downloader UX.

The downloader and transcription job slots are separate. Sending a stored video to transcription passes its existing file path to the old pipeline and gives that pipeline a distinct temporary working directory; transcription cleanup therefore cannot remove the stored original.

## Native fidelity

The direct adapter copies response bytes without FFmpeg rewriting. YouTube progressive streams are copied; adaptive tracks are muxed with FFmpeg `-c copy`, without transcoding. `reencoded=false` describes acquisition, and a successful decode is a technical check, not a judgment of perceived sharpness or editorial quality.

Twitch, Whop, Google Drive and generic HLS/DASH remain unavailable until authorized acquisition workflows are implemented and verified. YouTube real-source UAT is blocked in this environment because package-index DNS failed and Pytubefix is not installed.
