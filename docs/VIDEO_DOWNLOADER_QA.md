# Video Downloader QA Record

## Environment

- Windows PowerShell workspace.
- FFmpeg and FFprobe are available on `PATH`.
- Python runtime: `backend/.venv`.
- Frontend dependencies already present in `frontend/node_modules`.

## Checks executed

| Check | Result | Evidence |
|---|---|---|
| Backend syntax compilation | PASS | `python -m compileall -q backend` |
| Backend import / route registration | PASS | `import backend.main` |
| Downloader core tests | PASS | `python -m unittest discover -s backend/tests -p test_downloader.py -v` (11 offline tests, including mocked native YouTube quality discovery) |
| TypeScript typecheck | PASS | `npm run typecheck` |
| Next.js production build | PASS | `npm run build`; `/` and `/downloader` were generated |
| API real-source smoke | BLOCKED | Port 8000 rejected a second bind with Windows error 10048, and package DNS failure leaves Pytubefix unavailable |
| Browser navigation | PASS | Transkrip ↔ Video Downloader links navigate between pages using Next.js |
| Responsive browser UAT | PASS | Checked 1440×900, 768×1024, and 360×800; layout and controls fit each viewport |
| Existing pytest suite | NOT TESTED | `pytest` and `httpx` are absent. Installing `backend/requirements-dev.txt` was attempted but package index DNS/network access was unavailable |
| Pytubefix installation | BLOCKED | `pip install pytubefix==11.2.1` attempted once; configured package index hostname failed DNS resolution; no package in local pip cache |
| YouTube adapter | IMPLEMENTED, UAT BLOCKED | Native Pytubefix stream discovery and selected-format download/stream-copy mux are wired; runtime package absent, so supplied URL `https://youtu.be/0mr5_Jfv7NA` could not be acquired or benchmarked |
| Twitch | NOT AVAILABLE | Official Clip download API requires an eligible broadcaster/editor token and the appropriate scope; no credentials or authorized clip source configured |
| Whop | NOT AVAILABLE | No documented authenticated Content Library asset interface or owner-authorized test access configured |
| Google Drive | NOT AVAILABLE | OAuth/API credentials and authorized test file unavailable; original media download and `canDownload` check not implemented |
| HLS/DASH | NOT AVAILABLE | Manifest/segment downloader not implemented; no non-DRM authorized test manifest supplied |
| Real-source benchmark | NOT RUN | No acquisition could be performed. No quality/speed comparison or visual-frame claim is made |
| Graphify graph refresh | BLOCKED | `graphify update .` failed in the installed launcher with `uv trampoline failed to canonicalize script path` |

The downloader core tests exercise URL safeguards, filename sanitization, unknown inspection metadata, exact byte preservation, FFprobe/full-decode checks on generated video, persistence/hash in a synthetic worker job, and mocked YouTube format discovery. They do not cover or claim successful external provider acquisition. The API process could not be started because port 8000 is already bound, and external YouTube testing requires Pytubefix installation.

## Benchmark status

No alternative engine comparison was run because package-index DNS was unavailable and no authorized common source could be fetched. Pytubefix is selected for YouTube based on its documented native progressive/adaptive stream API, but it has not been benchmarked against yt-dlp on a common source. Direct downloads preserve the bytes offered by their source. No alternative quality or reliability superiority is claimed.
