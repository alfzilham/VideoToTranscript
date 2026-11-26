import { API_URL, checkedResponse } from "@/lib/api";

export interface DownloadFormat {
  format_id: string;
  label: string;
  width: number | null;
  height: number | null;
  fps: number | null;
  video_codec: string | null;
  audio_codec: string | null;
  container: string | null;
  estimated_size_bytes: number | null;
  native_original: boolean;
}

export interface Inspection {
  inspection_id: string;
  platform: string;
  title: string | null;
  duration_seconds: number | null;
  thumbnail_url: string | null;
  download_available: boolean;
  formats: DownloadFormat[];
  recommended_format_id: string | null;
  message: string | null;
}

export interface DownloadStatus {
  job_id: string;
  status: "queued" | "downloading" | "validating" | "done" | "error" | "cancelled";
  progress: number | null;
  downloaded_bytes: number;
  total_bytes: number | null;
  speed_bytes_per_second: number | null;
  eta_seconds: number | null;
  error_code: string | null;
  error_message: string | null;
}

export interface DownloadResult {
  job_id: string;
  filename: string;
  title: string | null;
  platform: string;
  file_size_bytes: number;
  duration_seconds: number | null;
  width: number | null;
  height: number | null;
  fps: number | null;
  video_codec: string | null;
  audio_codec: string | null;
  video_bitrate_bps: number | null;
  audio_bitrate_bps: number | null;
  container: string | null;
  acquisition_method: string;
  reencoded: boolean;
  full_decode_passed: boolean;
  sha256: string;
  file_url: string;
  preview_url: string;
  completed_at: string;
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  return checkedResponse<T>(await fetch(`${API_URL}${path}`, { cache: "no-store", ...init }));
}

export function formatBytes(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "Tidak tersedia";
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let size = value / 1024;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) { size /= 1024; unit += 1; }
  return `${size.toFixed(1)} ${units[unit]}`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "Tidak tersedia";
  const total = Math.floor(seconds);
  return [Math.floor(total / 3600), Math.floor((total % 3600) / 60), total % 60].map((part) => String(part).padStart(2, "0")).join(":");
}

export function formatBitrate(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "Tidak tersedia";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(2)} Mbps`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(0)} kbps`;
  return `${value} bps`;
}
