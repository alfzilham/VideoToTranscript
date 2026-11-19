# SPEC.md — Video to Transcript

## 1. Input

### 1.1 Input via URL YouTube
- Field teks untuk paste URL YouTube.
- Validasi format URL (harus domain youtube.com atau youtu.be).
- Setelah submit, backend memanggil `yt-dlp` untuk mengunduh video (format audio terbaik yang tersedia, atau video lalu diekstrak audionya).

### 1.2 Input via Upload File
- Komponen upload file (drag-and-drop atau klik pilih file).
- Format didukung: `.mp4`, `.mkv`, `.mov`, `.webm`, `.mp3`, `.wav`.
- Validasi ukuran file (batas disesuaikan dengan storage lokal, default maksimum 2GB — dapat dikonfigurasi).

## 2. Proses Pengolahan

### 2.1 Tahap Download (khusus input URL)
- `yt-dlp` mengunduh video/audio ke folder temporary lokal.
- Error handling: video private/unavailable/region-locked → tampilkan pesan error jelas ke UI.

### 2.2 Tahap Ekstraksi Audio
- `ffmpeg` mengekstrak audio dari file video menjadi format `.wav` (16kHz mono, format yang direkomendasikan untuk Whisper).
- Jika input sudah berupa file audio, tahap ini dilewati.

### 2.3 Tahap Transkripsi
- `faster-whisper` memproses file audio `.wav`.
- Model default: `small`. Opsi lain: `medium` (dapat dipilih user di UI).
- Output dari faster-whisper berupa list segmen, masing-masing memiliki:
  - `start` (waktu mulai, detik)
  - `end` (waktu selesai, detik)
  - `text` (isi ucapan)

### 2.4 Tahap Formatting Output
- Setiap segmen diformat menjadi baris:
  ```
  [00:00:02] Teks ucapan pertama di sini...
  [00:00:08] Lanjutan ucapan berikutnya...
  ```
- Format timestamp: `HH:MM:SS` (jam:menit:detik), dua digit masing-masing, dalam kurung siku.
- Baris dipisahkan dengan newline tunggal.

## 3. Output

- Transcript lengkap ditampilkan di area teks (scrollable) pada UI.
- Tombol **"Copy to Clipboard"** — menyalin seluruh teks transcript ke clipboard.
- Tombol **"Download as .txt"** — mengunduh file `.txt` dengan nama berdasarkan judul video/file asli (disanitasi dari karakter ilegal untuk nama file).

## 4. API Endpoints (Backend — FastAPI)

### `POST /api/process/url`
- Body: `{ "url": "https://youtube.com/watch?v=...", "model": "small" }`
- Response: `{ "job_id": "uuid" }`

### `POST /api/process/upload`
- Multipart form-data: file video/audio + field `model`.
- Response: `{ "job_id": "uuid" }`

### `GET /api/status/{job_id}`
- Response: `{ "status": "downloading" | "extracting" | "transcribing" | "done" | "error", "progress": 0-100, "error_message": string | null }`

### `GET /api/result/{job_id}`
- Response (jika status = done): `{ "transcript": "[00:00:02] ...\n[00:00:08] ...", "filename_suggestion": "judul-video.txt" }`

## 5. Error Handling

| Kasus | Perilaku |
|---|---|
| URL YouTube tidak valid | Tampilkan pesan "URL tidak valid" sebelum submit |
| Video private/unavailable | Status job = error, pesan: "Video tidak dapat diakses" |
| File upload melebihi batas ukuran | Tolak di sisi frontend sebelum upload, tampilkan pesan batas |
| Format file tidak didukung | Tolak dengan pesan format yang didukung |
| Proses transkripsi gagal (crash/out of memory) | Status job = error, pesan error teknis ditampilkan apa adanya di UI |

## 6. Non-Functional Requirements

- Aplikasi berjalan di `localhost`, port dapat dikonfigurasi (default backend: `8000`, frontend: `3000`).
- Tidak ada autentikasi.
- File temporary (video/audio yang diunduh/diupload) dibersihkan otomatis setelah job selesai, kecuali user memilih untuk menyimpan.
- Semua pemrosesan berjalan secara sinkron per job (tidak ada antrian job paralel di v1, karena hanya untuk 1 pengguna).
