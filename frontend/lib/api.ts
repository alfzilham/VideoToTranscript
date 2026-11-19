export type Model = "small" | "medium";
export type JobStatus = "downloading" | "extracting" | "transcribing" | "done" | "error";

export interface StatusResponse {
  status: JobStatus;
  progress: number;
  error_message: string | null;
}

export interface TranscriptResponse {
  transcript: string;
  filename_suggestion: string;
}

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
export const MAX_UPLOAD_BYTES = Number(process.env.NEXT_PUBLIC_MAX_UPLOAD_BYTES || "2147483648");
export const ALLOWED_EXTENSIONS = [".mp4", ".mkv", ".mov", ".webm", ".mp3", ".wav"];

export function isYoutubeUrl(value: string): boolean {
  try {
    const url = new URL(value.trim());
    const host = url.hostname.toLowerCase();
    return (
      (url.protocol === "http:" || url.protocol === "https:") &&
      (host === "youtube.com" || host.endsWith(".youtube.com") || host === "youtu.be") &&
      (url.port === "" || url.port === "80" || url.port === "443") &&
      !url.username && !url.password && url.pathname.replaceAll("/", "").length > 0
    );
  } catch {
    return false;
  }
}

export function getFileError(file: File): string | null {
  const ext = "." + (file.name.split(".").pop() || "").toLowerCase();
  if (!ALLOWED_EXTENSIONS.includes(ext)) {
    return "Format tidak didukung. Pilih MP4, MKV, MOV, WEBM, MP3, atau WAV.";
  }
  if (!Number.isFinite(MAX_UPLOAD_BYTES) || MAX_UPLOAD_BYTES <= 0) {
    return "Konfigurasi batas ukuran file tidak valid.";
  }
  if (file.size === 0) return "File tidak boleh kosong.";
  if (file.size > MAX_UPLOAD_BYTES) {
    return `Ukuran file melebihi batas ${Math.floor(MAX_UPLOAD_BYTES / 1024 ** 2)} MB.`;
  }
  return null;
}

export async function checkedResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    let error = `Permintaan gagal (HTTP ${response.status}).`;
    if (body && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail?: unknown }).detail;
      if (typeof detail === "string") error = detail;
    }
    throw new Error(error);
  }
  return (await response.json()) as T;
}
