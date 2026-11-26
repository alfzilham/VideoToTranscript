"use client";

import { useEffect, useRef, useState } from "react";
import InputForm from "@/components/InputForm";
import ProgressIndicator from "@/components/ProgressIndicator";
import TranscriptResult from "@/components/TranscriptResult";
import TopBar from "@/components/TopBar";
import { API_URL, checkedResponse } from "@/lib/api";
import type { Model, StatusResponse, TranscriptResponse } from "@/lib/api";

type InputPayload =
  | { mode: "url"; url: string; model: Model }
  | { mode: "upload"; file: File; model: Model };

export default function Home() {
  const [jobId, setJobId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [result, setResult] = useState<TranscriptResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [restored, setRestored] = useState(false);
  const busy = submitting || jobId !== null;
  const pollFailures = useRef(0);

  useEffect(() => {
    const savedJob = window.localStorage.getItem("vtt:transcription:jobId");
    if (savedJob) setJobId(savedJob);
    setRestored(true);
  }, []);

  async function submit(input: InputPayload) {
    if (busy) return;
    setSubmitting(true);
    setJobId(null);
    setResult(null);
    setError(null);
    setStatus(null);
    pollFailures.current = 0;
    try {
      let response: Response;
      if (input.mode === "url") {
        response = await fetch(`${API_URL}/api/process/url`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url: input.url, model: input.model }),
        });
      } else {
        const formData = new FormData();
        formData.append("file", input.file);
        formData.append("model", input.model);
        response = await fetch(`${API_URL}/api/process/upload`, { method: "POST", body: formData });
      }
      const data = await checkedResponse<{ job_id: string }>(response);
      window.localStorage.setItem("vtt:transcription:jobId", data.job_id);
      setJobId(data.job_id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Gagal mengirim permintaan.");
    } finally {
      setSubmitting(false);
    }
  }

  useEffect(() => {
    if (!jobId) return;
    let live = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const controller = new AbortController();

    async function poll() {
      if (!live) return;
      try {
        const response = await fetch(`${API_URL}/api/status/${encodeURIComponent(jobId!)}`, {
          signal: controller.signal, cache: "no-store",
        });
        const next = await checkedResponse<StatusResponse>(response);
        if (!live) return;
        pollFailures.current = 0;
        setStatus(next);
        if (next.status === "error") {
          setError(next.error_message || "Proses transkripsi gagal.");
          setJobId(null);
          window.localStorage.removeItem("vtt:transcription:jobId");
          return;
        }
        if (next.status === "done") {
          const final = await checkedResponse<TranscriptResponse>(
            await fetch(`${API_URL}/api/result/${encodeURIComponent(jobId!)}`, { signal: controller.signal, cache: "no-store" })
          );
          if (!live) return;
          setResult(final);
          setJobId(null);
          window.localStorage.removeItem("vtt:transcription:jobId");
          return;
        }
      } catch (cause) {
        if (!live || controller.signal.aborted) return;
        pollFailures.current += 1;
        if (pollFailures.current >= 4) {
          setError(cause instanceof Error ? `Koneksi backend gagal: ${cause.message}` : "Koneksi backend terputus.");
          setJobId(null);
          window.localStorage.removeItem("vtt:transcription:jobId");
          return;
        }
      }
      if (live) timer = setTimeout(poll, 2000);
    }

    void poll();
    return () => {
      live = false;
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [jobId]);

  return (
    <main className="app-shell">
      <TopBar />
      <header className="app-header">
        <span className="app-eyebrow">LOCAL WORKSPACE / SPEECH-TO-TEXT</span>
        <div className="app-brand"><h1>Video to Transcript<span className="title-dot">.</span></h1></div>
        <p className="app-intro">Ubah video menjadi teks bertimestamp, langsung siap digunakan sebagai konteks percakapan AI.</p>
        <div className="app-meta"><span className="meta-indicator" /> 100% diproses di perangkat Anda <span className="meta-divider">/</span> CPU-only</div>
      </header>

      <InputForm busy={busy} onSubmit={submit} />
      <ProgressIndicator status={status} busy={busy} />
      {error && (
        <section className="alert-box" role="alert">
          <strong>[!] Proses tidak berhasil</strong>
          <p>{error}</p>
        </section>
      )}
      <TranscriptResult key={result?.filename_suggestion ?? "none"} result={result} />
      {restored && !result && !busy && !error && (
        <section className="empty-result" aria-label="Hasil transcript belum tersedia">
          <span className="empty-symbol" aria-hidden="true">[ 00:00:00 ]</span>
          <p>Transcript Anda akan muncul di sini setelah video diproses.</p>
        </section>
      )}
      <footer className="footer">Video to Transcript <span aria-hidden="true">·</span> Open Source <span aria-hidden="true">·</span> Localhost</footer>
    </main>
  );
}
