"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import TopBar from "@/components/TopBar";
import { API_URL, checkedResponse } from "@/lib/api";
import { api, formatBitrate, formatBytes, formatDuration } from "@/lib/downloader-api";
import type { DownloadFormat, DownloadResult, DownloadStatus, Inspection } from "@/lib/downloader-api";

const ACTIVE_KEY = "vtt:downloader:jobId";
const TRANSCRIPTION_KEY = "vtt:transcription:jobId";

export default function VideoDownloaderPage() {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [inspection, setInspection] = useState<Inspection | null>(null);
  const [formatId, setFormatId] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [status, setStatus] = useState<DownloadStatus | null>(null);
  const [result, setResult] = useState<DownloadResult | null>(null);
  const [history, setHistory] = useState<DownloadResult[]>([]);
  const [model, setModel] = useState<"small" | "medium">("small");
  const [busyInspect, setBusyInspect] = useState(false);
  const [startingDownload, setStartingDownload] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [restored, setRestored] = useState(false);

  const loadHistory = useCallback(async () => {
    try { setHistory(await api<DownloadResult[]>("/api/downloader/history")); } catch { /* The history panel remains usable if the API is offline. */ }
  }, []);

  useEffect(() => {
    const saved = window.localStorage.getItem(ACTIVE_KEY);
    if (saved) setJobId(saved);
    setRestored(true);
    void loadHistory();
  }, [loadHistory]);

  useEffect(() => {
    if (!jobId) return;
    let live = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const controller = new AbortController();
    let failures = 0;
    const poll = async () => {
      if (!live) return;
      try {
        const next = await api<DownloadStatus>(`/api/downloader/status/${encodeURIComponent(jobId)}`, { signal: controller.signal });
        if (!live) return;
        failures = 0;
        setStatus(next);
        if (next.status === "done") {
          const final = await api<DownloadResult>(`/api/downloader/result/${encodeURIComponent(jobId)}`, { signal: controller.signal });
          if (!live) return;
          setResult(final);
          setJobId(null);
          window.localStorage.removeItem(ACTIVE_KEY);
          void loadHistory();
          return;
        }
        if (next.status === "error" || next.status === "cancelled") {
          setError(next.error_message || (next.status === "cancelled" ? "Unduhan dibatalkan." : "Unduhan gagal."));
          setJobId(null);
          window.localStorage.removeItem(ACTIVE_KEY);
          void loadHistory();
          return;
        }
      } catch (cause) {
        if (!live || controller.signal.aborted) return;
        failures += 1;
        if (failures >= 4) {
          setError(cause instanceof Error ? `Status unduhan tidak dapat diperiksa: ${cause.message}` : "Status unduhan tidak dapat diperiksa.");
          setJobId(null);
          window.localStorage.removeItem(ACTIVE_KEY);
          return;
        }
      }
      if (live) timer = setTimeout(poll, 1000);
    };
    void poll();
    return () => { live = false; controller.abort(); if (timer) clearTimeout(timer); };
  }, [jobId, loadHistory]);

  async function inspectSource(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null); setResult(null); setInspection(null); setStatus(null); setBusyInspect(true);
    try {
      const next = await api<Inspection>("/api/downloader/inspect", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url: url.trim() }),
      });
      setInspection(next);
      const recommended = next.recommended_format_id ?? next.formats[0]?.format_id ?? "";
      setFormatId(recommended);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Gagal memeriksa URL."); }
    finally { setBusyInspect(false); }
  }

  async function startDownload() {
    if (!inspection || !formatId || jobId) return;
    setStartingDownload(true);
    setError(null); setResult(null); setStatus({ job_id: "", status: "queued", progress: 0, downloaded_bytes: 0, total_bytes: inspection.formats.find((item) => item.format_id === formatId)?.estimated_size_bytes ?? null, speed_bytes_per_second: null, eta_seconds: null, error_code: null, error_message: null });
    try {
      const accepted = await api<{ job_id: string; status: string }>("/api/downloader/download", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ inspection_id: inspection.inspection_id, format_id: formatId }),
      });
      window.localStorage.setItem(ACTIVE_KEY, accepted.job_id);
      setJobId(accepted.job_id);
    } catch (cause) { setStatus(null); setError(cause instanceof Error ? cause.message : "Unduhan tidak dapat dimulai."); }
    finally { setStartingDownload(false); }
  }

  async function cancelDownload() {
    if (!jobId) return;
    try { await api(`/api/downloader/cancel/${encodeURIComponent(jobId)}`, { method: "POST" }); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Unduhan tidak dapat dibatalkan."); }
  }

  async function sendToTranscript(downloadId: string) {
    setError(null);
    try {
      const accepted = await api<{ job_id: string }>(`/api/downloader/transcribe/${encodeURIComponent(downloadId)}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model }),
      });
      window.localStorage.setItem(TRANSCRIPTION_KEY, accepted.job_id);
      router.push("/");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Transkripsi tidak dapat dimulai."); }
  }

  async function downloadMetadata(downloadId: string) {
    try {
      const data = await api<DownloadResult>(`/api/downloader/metadata/${encodeURIComponent(downloadId)}`);
      const anchor = document.createElement("a");
      anchor.href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
      anchor.download = `${data.filename.replace(/\.[^.]+$/, "")}-metadata.json`;
      anchor.click();
      URL.revokeObjectURL(anchor.href);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Metadata tidak dapat diunduh."); }
  }

  function renderInspector(media: DownloadResult) {
    const fields: Array<[string, string]> = [
      ["Resolusi", media.width && media.height ? `${media.width} × ${media.height}` : "Tidak tersedia"],
      ["Frame rate", media.fps ? `${media.fps} fps` : "Tidak tersedia"],
      ["Video codec", media.video_codec || "Tidak tersedia"], ["Audio codec", media.audio_codec || "Tidak tersedia"],
      ["Bitrate video", formatBitrate(media.video_bitrate_bps)], ["Bitrate audio", formatBitrate(media.audio_bitrate_bps)],
      ["Container", media.container || "Tidak tersedia"], ["Durasi", formatDuration(media.duration_seconds)],
      ["Ukuran file", formatBytes(media.file_size_bytes)], ["Metode", media.acquisition_method],
      ["Re-encode", media.reencoded ? "Ya" : "Tidak"], ["Full decode", media.full_decode_passed ? "PASS" : "FAIL"],
      ["SHA-256", media.sha256],
    ];
    return <dl className="quality-grid">{fields.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>;
  }

  const stage = status?.status === "queued" ? "Menyiapkan" : status?.status === "downloading" ? "Mengunduh" : status?.status === "validating" ? "Memvalidasi" : status?.status === "done" ? "Selesai" : "";
  const active = Boolean(jobId);
  const progress = status?.progress;

  return (
    <main className="app-shell">
      <TopBar />
      <header className="app-header">
        <span className="app-eyebrow">LOCAL WORKSPACE / NATIVE QUALITY DOWNLOAD</span>
        <div className="app-brand"><h1>Video Downloader<span className="title-dot">.</span></h1></div>
        <p className="app-intro">Unduh video dengan kualitas sumber tertinggi tanpa kompresi yang tidak diperlukan.</p>
        <div className="app-meta"><span className="meta-indicator" /> Local Processing <span className="meta-divider">/</span> Original Quality</div>
      </header>

      <section className="panel" aria-labelledby="source-heading">
        <h2 id="source-heading" className="section-title">Sumber video</h2>
        <p className="section-note">Masukkan URL file video langsung atau sumber yang telah dikenali.</p>
        <form onSubmit={inspectSource}>
          <div className="field downloader-url-field">
            <label htmlFor="download-url">URL video</label>
            <input id="download-url" type="url" required maxLength={4096} value={url} disabled={busyInspect || startingDownload || active} onChange={(event) => setUrl(event.target.value)} placeholder="https://example.com/video.mp4" aria-describedby="source-helper" />
            <span id="source-helper" className="helper">File langsung dapat diperiksa. Provider lain hanya tersedia jika alur resmi dan terotorisasi telah dikonfigurasi.</span>
          </div>
          <button className="primary-button downloader-submit" type="submit" disabled={busyInspect || startingDownload || active || !url.trim()}>{busyInspect ? "Memeriksa…" : "Periksa Video"}</button>
        </form>
      </section>

      {inspection && <section className="panel" aria-labelledby="inspection-heading">
        <div className="result-heading-row"><div><h2 id="inspection-heading" className="section-title">Informasi sumber</h2><p className="section-note">Platform: {inspection.platform.replace("_", " ")}</p></div>{inspection.title && <span className="result-tag">{inspection.title}</span>}</div>
        {inspection.thumbnail_url && <img className="source-thumbnail" src={inspection.thumbnail_url} alt="Thumbnail sumber video" />}
        <div className="source-facts"><span>Durasi: {formatDuration(inspection.duration_seconds)}</span><span>Perkiraan ukuran: {formatBytes(inspection.formats.find((item) => item.format_id === formatId)?.estimated_size_bytes)}</span></div>
        {inspection.formats.length > 0 && <div className="field quality-select-field"><label htmlFor="quality-select">Kualitas yang tersedia</label><select id="quality-select" value={formatId} onChange={(event) => setFormatId(event.target.value)} disabled={active}>{inspection.formats.map((format: DownloadFormat) => <option key={format.format_id} value={format.format_id}>{format.label}</option>)}</select></div>}
        {inspection.message && <p className="helper source-message">{inspection.message}</p>}
        {inspection.download_available && <button className="primary-button" type="button" onClick={startDownload} disabled={active || startingDownload || !formatId}>{startingDownload ? "Menyiapkan…" : "Download Video"}</button>}
      </section>}

      {status && <section className="panel progress-panel" aria-label="Progres unduhan" aria-live="polite">
        <div className="progress-topline"><span className="progress-label">{stage}</span><span className="progress-value">{progress === null ? "—" : `${progress}%`}</span></div>
        <div className="progress-track" role="progressbar" aria-label="Progres unduhan" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress ?? undefined} aria-valuetext={progress === null ? `${formatBytes(status.downloaded_bytes)} diunduh` : `${progress}%`}><div className={progress === null ? "progress-fill progress-indeterminate" : "progress-fill"} style={progress === null ? undefined : { width: `${progress}%` }} /></div>
        <p className="helper">{formatBytes(status.downloaded_bytes)} diunduh / {formatBytes(status.total_bytes)} · {status.speed_bytes_per_second ? `${formatBytes(status.speed_bytes_per_second)}/s` : "Kecepatan tidak tersedia"} · {status.eta_seconds === null ? "Sisa waktu tidak tersedia" : `${status.eta_seconds} dtk tersisa`}</p>
        {active && <button type="button" className="secondary-button cancel-button" onClick={cancelDownload}>Batalkan unduhan</button>}
      </section>}

      {error && <section className="alert-box" role="alert"><strong>[!] Proses tidak berhasil</strong><p>{error}</p></section>}

      {result && <section className="panel result-panel" aria-labelledby="download-result-heading">
        <h2 id="download-result-heading" className="section-title">Hasil unduhan</h2>
        <p className="section-note">Validasi teknis berhasil. Ini tidak menilai ketajaman atau kualitas visual perseptual.</p>
        <video className="download-preview" controls preload="metadata" src={`${API_URL}${result.preview_url}`} aria-label={`Pratinjau ${result.filename}`}>
          Browser ini tidak mendukung codec file. File asli tetap tersedia untuk diunduh.
        </video>
        {renderInspector(result)}
        <div className="result-actions">
          <a className="primary-button action-link" href={`${API_URL}${result.file_url}`}>Download Video</a>
          <button type="button" className="secondary-button" onClick={() => void downloadMetadata(result.job_id)}>Download Metadata</button>
          <button type="button" className="secondary-button" onClick={() => void sendToTranscript(result.job_id)}>Send to Transcript</button>
          <button type="button" className="secondary-button" onClick={() => { setResult(null); setInspection(null); setStatus(null); setUrl(""); setError(null); }}>Download Another Video</button>
        </div>
        <p className="helper">Jika codec tidak kompatibel dengan browser, gunakan file asli melalui tombol Download Video.</p>
      </section>}

      {!result && !active && !inspection && !error && restored && <section className="empty-result" aria-label="Belum ada hasil download"><span className="empty-symbol" aria-hidden="true">[ VIDEO ]</span><p>Informasi dan hasil download akan muncul di sini.</p></section>}

      <section className="panel history-panel" aria-labelledby="history-heading">
        <div className="result-heading-row"><div><h2 id="history-heading" className="section-title">Riwayat download</h2><p className="section-note">Hasil tersimpan lokal dan bertahan setelah backend dimulai ulang.</p></div><button type="button" className="secondary-button history-refresh" onClick={() => void loadHistory()}>Perbarui</button></div>
        {history.length === 0 ? <p className="helper history-empty">Belum ada download yang selesai.</p> : <ul className="history-list">{history.map((item) => <li key={item.job_id}>
          <div className="history-item-main"><strong>{item.title || item.filename}</strong><span>{item.platform} · {item.width && item.height ? `${item.width} × ${item.height}` : "Resolusi tidak tersedia"} · {formatBytes(item.file_size_bytes)}</span><time dateTime={item.completed_at}>{new Date(item.completed_at).toLocaleString("id-ID")}</time></div>
          <div className="history-actions"><a className="text-action" href={`${API_URL}${item.file_url}`}>Unduh</a><button className="text-action" type="button" onClick={() => void sendToTranscript(item.job_id)}>Transkripkan</button></div>
        </li>)}</ul>}
      </section>

      <section className="panel transcript-send-panel" aria-label="Pengaturan transkripsi">
        <div className="field"><label htmlFor="transcript-model">Model Whisper untuk Send to Transcript</label><select id="transcript-model" value={model} onChange={(event) => setModel(event.target.value as "small" | "medium")}><option value="small">small</option><option value="medium">medium</option></select></div>
      </section>
      <footer className="footer">Video to Transcript <span aria-hidden="true">·</span> Open Source <span aria-hidden="true">·</span> Localhost</footer>
    </main>
  );
}
