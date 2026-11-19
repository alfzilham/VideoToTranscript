"use client";

import type { StatusResponse } from "@/lib/api";

interface ProgressIndicatorProps {
  status: StatusResponse | null;
  busy: boolean;
}

const labels = {
  downloading: "Mengunduh video...",
  extracting: "Mengekstrak audio...",
  transcribing: "Mentranskripsi...",
  done: "Selesai",
  error: "Gagal memproses",
} as const;

export default function ProgressIndicator({ status, busy }: ProgressIndicatorProps) {
  if (!busy && status?.status !== "done") return null;
  const progress = Math.min(100, Math.max(0, Math.round(status?.progress ?? 0)));
  const label = status ? labels[status.status] : "Menyiapkan pekerjaan...";
  return (
    <section className="panel progress-panel" aria-label="Status pemrosesan" aria-live="polite">
      <div className="progress-topline">
        <span className="progress-label">{label}</span>
        <span className="progress-value">{progress}%</span>
      </div>
      <div
        className="progress-track" role="progressbar" aria-label="Progres pemrosesan"
        aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}
      >
        <div className="progress-fill" style={{ width: `${progress}%` }} />
      </div>
      <p className="helper">Persentase adalah perkiraan per tahap. Transkripsi CPU dapat memerlukan waktu cukup lama.</p>
    </section>
  );
}
