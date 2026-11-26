# Video Downloader Workflow

1. Enter a URL and request inspection.
2. Backend validates HTTP(S), resolves the host, rejects private/internal IP addresses, and uses an IP-pinned connection. Redirect targets are checked the same way.
3. YouTube URLs are inspected through Pytubefix and expose discovered native formats; direct files are checked via HEAD, or a one-byte range request if HEAD is unavailable. Providers without a configured authorized adapter report unavailable.
4. Select a discovered rendition. The server rechecks availability and format selection before starting.
5. The worker streams to a unique `.part` file, reports observed byte/speed/ETA values, and watches for cancellation. YouTube adaptive tracks use FFmpeg stream copy without re-encoding.
6. FFprobe obtains actual stream/container metadata. FFmpeg fully decodes the file. Incomplete, oversized, non-video, or undecodable files are rejected.
7. A SHA-256 and manifest are saved beside the original bytes. History reads those manifests after restart.
8. The UI can preview compatible codecs, download media/metadata, or pass the persistent file into the existing transcription pipeline.

Switching pages retains the active transcription/downloader job ID in browser local storage. The backend itself keeps live worker state in memory, so restarting the backend ends active jobs; completed media and history remain on disk.
