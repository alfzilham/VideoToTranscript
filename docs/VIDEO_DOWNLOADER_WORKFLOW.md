# Video Downloader Workflow

1. Enter a URL and request inspection.
2. Backend validates HTTP(S), resolves the host, rejects private/internal IP addresses, and uses an IP-pinned connection. Redirect targets and each HLS/DASH media resource are checked the same way.
3. YouTube URLs are inspected through Pytubefix and expose discovered native formats; direct files are checked via HEAD, or a one-byte range request if HEAD is unavailable. Twitch Clips use the official Helix API for a token whose user is authorized for that Clip. Google Drive uses Drive API OAuth, checks `canDownload`, and retrieves the original blob. HLS/DASH inspects supported static manifests. Whop is `SKIPPED_BY_OWNER` and is not processed.
4. Select a discovered rendition. The server rechecks availability and format selection before enqueueing the job.
5. The worker streams to a unique `.part` file, reports observed byte/speed/ETA values, and watches for cancellation. YouTube adaptive tracks and HLS/DASH tracks use FFmpeg stream copy without re-encoding.
6. FFprobe obtains actual stream/container metadata. FFmpeg fully decodes the file. Incomplete, oversized, non-video, or undecodable files are rejected.
7. A SHA-256 and manifest are saved beside the original bytes. History reads those manifests after restart.
8. The UI can preview compatible codecs, download media/metadata, or pass the persistent file into the existing transcription pipeline.

## Final UAT status

Direct media, YouTube, Google Drive, HLS VOD, and DASH VOD have real-source acquisition and validation evidence recorded in `docs/VIDEO_DOWNLOADER_QA.md`. Direct, Drive, YouTube, HLS and DASH handoffs to the existing transcription pipeline completed. Twitch authentication passes and its Clip adapter is optional; the official API only supplies media to an authorized broadcaster/editor for the target channel. This restriction is not a production blocker. Edge plays the tested preview URL with valid MP4 range delivery; the prior inline fallback was not reproduced. Whop is skipped at the owner's direction.

Switching pages retains the active transcription/downloader job ID in browser local storage. `GET /api/worker/status` and each job status endpoint report the FIFO queue, active job, stage, progress, and worker availability. A queued transcription resumes after backend restart if its input still exists; an active transcription is marked `interrupted`. A nonterminal download is also marked `interrupted`, and is not automatically restarted. Completed media/history and transcription job status/results remain persisted locally.

## External Clipper Agent handoff

Run VTT with `vtt-activate`, then have the separate Agent call the local API sequence documented in `docs/VIDEO_DOWNLOADER_API.md`: inspect source → select a returned native format → start download → poll status → read result and `file_url`. The Agent can use the persistent original and verified metadata; it may then request VTT transcription for a stored download and poll the transcription job. Both processes must run on the same computer because the API binds to loopback and has no authentication.
