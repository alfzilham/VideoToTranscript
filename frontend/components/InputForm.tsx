"use client";

import { useRef, useState } from "react";
import type { ChangeEvent, DragEvent, FormEvent, KeyboardEvent } from "react";
import { ALLOWED_EXTENSIONS, getFileError, isYoutubeUrl } from "@/lib/api";
import type { Model } from "@/lib/api";

type InputMode = "url" | "upload";

interface InputFormProps {
  busy: boolean;
  onSubmit: (input: { mode: "url"; url: string; model: Model } | { mode: "upload"; file: File; model: Model }) => void;
}

export default function InputForm({ busy, onSubmit }: InputFormProps) {
  const [mode, setMode] = useState<InputMode>("url");
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [model, setModel] = useState<Model>("small");
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const tabUrl = useRef<HTMLButtonElement>(null);
  const tabUpload = useRef<HTMLButtonElement>(null);

  function switchMode(next: InputMode) {
    if (busy) return;
    setError(null);
    setMode(next);
  }

  function onTabKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (busy) return;
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      const next: InputMode = mode === "url" ? "upload" : "url";
      switchMode(next);
      (next === "url" ? tabUrl : tabUpload).current?.focus();
    }
  }

  function chooseFile(next: File | null) {
    if (!next) return;
    const problem = getFileError(next);
    setError(problem);
    setFile(problem ? null : next);
  }

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    chooseFile(event.currentTarget.files?.[0] ?? null);
  }

  function onFileDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    if (busy) return;
    chooseFile(event.dataTransfer.files?.[0] ?? null);
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (busy) return;
    if (mode === "url") {
      if (!isYoutubeUrl(url)) {
        setError("URL tidak valid. Gunakan tautan youtube.com atau youtu.be.");
        return;
      }
      onSubmit({ mode: "url", url: url.trim(), model });
    } else {
      if (!file) {
        setError("Pilih file video atau audio terlebih dahulu.");
        return;
      }
      const problem = getFileError(file);
      if (problem) {
        setError(problem);
        return;
      }
      onSubmit({ mode: "upload", file, model });
    }
  }

  return (
    <section className="panel" aria-labelledby="input-heading">
      <h2 id="input-heading" className="section-title">Sumber video</h2>
      <p className="section-note">Pilih tautan YouTube atau file dari perangkat Anda.</p>
      <div className="tab-list" role="tablist" aria-label="Jenis sumber video">
        <button
          ref={tabUrl} type="button" role="tab" id="tab-url"
          aria-selected={mode === "url"} aria-controls="panel-url"
          tabIndex={mode === "url" ? 0 : -1} disabled={busy}
          className={`tab ${mode === "url" ? "tab-active" : ""}`}
          onClick={() => switchMode("url")} onKeyDown={onTabKeyDown}
        >URL YouTube</button>
        <button
          ref={tabUpload} type="button" role="tab" id="tab-upload"
          aria-selected={mode === "upload"} aria-controls="panel-upload"
          tabIndex={mode === "upload" ? 0 : -1} disabled={busy}
          className={`tab ${mode === "upload" ? "tab-active" : ""}`}
          onClick={() => switchMode("upload")} onKeyDown={onTabKeyDown}
        >Upload File</button>
      </div>
      <form onSubmit={submit} noValidate>
        {mode === "url" ? (
          <div id="panel-url" role="tabpanel" aria-labelledby="tab-url" className="field">
            <label htmlFor="youtube-url">URL video YouTube</label>
            <input
              id="youtube-url" type="url" value={url} disabled={busy}
              onChange={(event) => { setUrl(event.target.value); setError(null); }}
              placeholder="https://www.youtube.com/watch?v=..."
              aria-invalid={Boolean(error)} aria-describedby={error ? "input-error" : "url-helper"}
              autoComplete="url"
            />
            <span className="helper" id="url-helper">Video publik yang dapat diakses yt-dlp.</span>
          </div>
        ) : (
          <div id="panel-upload" role="tabpanel" aria-labelledby="tab-upload" className="field">
            <label htmlFor="video-file">File video atau audio</label>
            <div
              className={`dropzone ${dragging ? "dropzone-active" : ""} ${busy ? "dropzone-disabled" : ""}`}
              onDragEnter={(event) => { event.preventDefault(); if (!busy) setDragging(true); }}
              onDragOver={(event) => event.preventDefault()}
              onDragLeave={(event) => { event.preventDefault(); setDragging(false); }}
              onDrop={onFileDrop}
            >
              <input
                ref={fileInput} id="video-file" type="file" disabled={busy}
                accept={ALLOWED_EXTENSIONS.join(",")}
                onChange={onFileChange} aria-invalid={Boolean(error)}
                aria-describedby={error ? "input-error" : "file-helper"}
              />
              <div className="upload-copy" aria-hidden="true">
                <span className="upload-glyph">+</span>
                <strong>{file?.name || "Klik atau tarik file ke sini"}</strong>
                <span>{file ? `${(file.size / (1024 * 1024)).toFixed(2)} MB dipilih` : "MP4, MKV, MOV, WEBM, MP3, WAV"}</span>
              </div>
            </div>
            <span className="helper" id="file-helper">Batas default: 2 GB. File tetap di perangkat lokal Anda.</span>
          </div>
        )}
        <div className="field model-field">
          <label htmlFor="whisper-model">Model Whisper</label>
          <select
            id="whisper-model" value={model} disabled={busy}
            onChange={(event) => setModel(event.target.value as Model)}
          >
            <option value="small">small (lebih cepat)</option>
            <option value="medium">medium (lebih akurat, lebih lambat)</option>
          </select>
        </div>
        {error && <p id="input-error" role="alert" className="error-text">[!] {error}</p>}
        <button
          className="primary-button" type="submit"
          disabled={busy || (mode === "url" ? !url.trim() : !file)}
        >{busy ? "Memproses..." : "Proses Video"}</button>
      </form>
    </section>
  );
}
