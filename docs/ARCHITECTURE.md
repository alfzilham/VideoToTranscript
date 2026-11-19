# ARCHITECTURE.md — Video to Transcript

## 1. Gambaran Umum

Aplikasi terdiri dari 2 komponen utama yang berjalan lokal:

```
┌─────────────────────┐         ┌──────────────────────────┐
│   Frontend (Next.js) │  HTTP   │   Backend (FastAPI)       │
│   localhost:3000     │ ──────► │   localhost:8000          │
└─────────────────────┘         └──────────────────────────┘
                                          │
                 ┌────────────────────────┼────────────────────────┐
                 ▼                        ▼                        ▼
          ┌─────────────┐         ┌──────────────┐        ┌─────────────────┐
          │   yt-dlp     │         │   ffmpeg      │        │  faster-whisper  │
          │ (download)   │         │ (extract wav) │        │  (transcription) │
          └─────────────┘         └──────────────┘        └─────────────────┘
```

## 2. Komponen

### 2.1 Frontend — Next.js
- Halaman tunggal (single page) dengan:
  - Form input (tab/toggle antara URL dan Upload).
  - Pemilihan model Whisper (dropdown: small/medium).
  - Progress indicator (polling status job ke backend).
  - Text area hasil transcript.
  - Tombol Copy & Download.
- Komunikasi ke backend via REST API (fetch).
- State management sederhana (React state/hooks, tidak perlu Redux untuk skala ini).

### 2.2 Backend — FastAPI (Python)
- Menerima request dari frontend (URL atau file upload).
- Mengelola job pemrosesan secara in-memory (dictionary `job_id` → status), karena hanya single-user dan tidak butuh database persisten.
- Menjalankan pipeline pemrosesan:
  1. `yt-dlp` (jika input URL) — download video/audio.
  2. `ffmpeg` — ekstraksi audio ke `.wav`.
  3. `faster-whisper` — transkripsi audio ke segmen teks+timestamp.
  4. Formatter — ubah segmen jadi teks final.
- Menyimpan hasil sementara di folder lokal (`/tmp/vtt-jobs/{job_id}/`).
- Endpoint status untuk polling progres dari frontend.

### 2.3 Processing Pipeline (Detail Alur)

```
Input (URL/File)
     │
     ▼
[yt-dlp download]  (dilewati jika input = file upload)
     │
     ▼
[ffmpeg extract audio → .wav 16kHz mono]
     │
     ▼
[faster-whisper transcribe → segments[{start, end, text}]]
     │
     ▼
[Formatter → "[HH:MM:SS] text" per baris]
     │
     ▼
Output disimpan di job result, siap diambil frontend
```

## 3. Keputusan Teknis & Alasan

| Keputusan | Alasan |
|---|---|
| FastAPI untuk backend | Python native, kompatibel langsung dengan `yt-dlp`, `ffmpeg-python`, dan `faster-whisper` tanpa perlu binding lintas bahasa |
| Next.js untuk frontend | Sesuai preferensi, developer experience baik, mudah dikembangkan jadi fitur tambahan nantinya |
| `faster-whisper` bukan `openai-whisper` | Implementasi CTranslate2 jauh lebih cepat di CPU (tanpa GPU/CUDA, sesuai spek laptop pengguna: AMD Ryzen 7 5825U, integrated graphics) |
| Job disimpan in-memory, bukan database | Skala personal, single-user, tidak butuh persistensi lintas restart server |
| Tidak ada WebSocket, pakai polling | Lebih sederhana untuk implementasi awal; job pemrosesan video tidak butuh update real-time per detik, polling tiap beberapa detik cukup |
| File temporary dibersihkan otomatis | Mencegah penumpukan file video/audio besar di laptop pengguna |

## 4. Struktur Folder (Diusulkan)

```
video-to-transcript/
├── backend/
│   ├── main.py                 # FastAPI app & routes
│   ├── pipeline/
│   │   ├── downloader.py       # wrapper yt-dlp
│   │   ├── extractor.py        # wrapper ffmpeg
│   │   ├── transcriber.py      # wrapper faster-whisper
│   │   └── formatter.py        # format segmen → teks timestamp
│   ├── jobs.py                 # job state management (in-memory)
│   └── requirements.txt
├── frontend/
│   ├── app/
│   │   └── page.tsx            # halaman utama
│   ├── components/
│   │   ├── InputForm.tsx
│   │   ├── ProgressIndicator.tsx
│   │   └── TranscriptResult.tsx
│   └── package.json
├── README.md
└── docs/
    ├── SPEC.md
    ├── ARCHITECTURE.md
    ├── DESIGN.md
    ├── CONTEXT.md
    ├── PRD.md
    └── WORKFLOW.md
```

## 5. Dependensi Eksternal

- `yt-dlp` — download video YouTube.
- `ffmpeg` (binary, harus terinstall di sistem) — ekstraksi audio.
- `faster-whisper` — transkripsi speech-to-text lokal.
- Model Whisper diunduh otomatis oleh `faster-whisper` saat pertama kali dipakai (disimpan di cache lokal).

## 6. Batasan Arsitektur (By Design)

- Tidak dirancang untuk banyak job paralel — cocok untuk 1 pengguna, 1 job pada satu waktu.
- Tidak ada layer autentikasi karena tidak ada kebutuhan multi-user.
- Tidak ada container/Docker di v1 (bisa ditambahkan belakangan jika dibutuhkan portabilitas lebih untuk kontributor open source).
