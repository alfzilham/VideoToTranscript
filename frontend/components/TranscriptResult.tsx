"use client";

import { useState } from "react";
import type { TranscriptResponse } from "@/lib/api";

interface TranscriptResultProps {
  result: TranscriptResponse | null;
}

export default function TranscriptResult({ result }: TranscriptResultProps) {
  const [copied, setCopied] = useState(false);
  if (!result) return null;

  async function copyTranscript() {
    try {
      await navigator.clipboard.writeText(result!.transcript);
      setCopied(true);
    } catch {
      setCopied(false);
      // The browser may disallow clipboard access on non-secure origins.
      alert("Tidak dapat menyalin otomatis. Pilih teks lalu salin secara manual.");
    }
  }

  function downloadTranscript() {
    if (!result) return;
    const blob = new Blob([result.transcript], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = result.filename_suggestion;
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return (
    <section className="panel result-panel" aria-labelledby="result-heading">
      <div className="result-heading-row">
        <div>
          <h2 id="result-heading" className="section-title">Hasil transcript</h2>
          <p className="section-note">Format timestamp siap ditempel sebagai konteks AI.</p>
        </div>
        <span className="result-tag">.txt</span>
      </div>
      <pre className="transcript-output" tabIndex={0} aria-label="Teks transcript">{result.transcript || "[Tidak ada ucapan yang dikenali pada audio.]"}</pre>
      <div className="result-actions">
        <button type="button" className="primary-button" onClick={copyTranscript}>
          {copied ? "Tersalin!" : "Copy to Clipboard"}
        </button>
        <button type="button" className="secondary-button" onClick={downloadTranscript}>
          Download as .txt
        </button>
      </div>
    </section>
  );
}
