<p align="center">
  <img src="./frontend/public/brand-lockup.png" alt="Video to Transcript" width="560" />
</p>

# Video to Transcript

Aplikasi web open source untuk mengubah **video YouTube** atau **file video/audio lokal** menjadi transkrip teks bertimestamp, misalnya:

```text
[00:00:02] Halo, selamat datang.
[00:00:08] Ini adalah contoh transkrip video.
```

Hasil dapat disalin dengan satu klik atau diunduh sebagai file `.txt` untuk diberikan sebagai konteks kepada AI berbasis teks. Pemrosesan transkripsi dilakukan **secara lokal di CPU** memakai `faster-whisper`, tanpa API berbayar.

> **Penggunaan personal dan lokal.** Aplikasi ini ditujukan untuk satu pengguna di `localhost`. Tidak memiliki autentikasi, manajemen multi-user, ataupun perlindungan untuk deployment server publik. Jangan membuka port backend/frontend untuk jaringan publik. Pastikan Anda berhak mengunduh dan memproses media yang digunakan, serta mengikuti persyaratan platform dan hukum yang berlaku.

**Aset brand:** `frontend/public/logo.webp` (logo di aplikasi), `frontend/public/favicon.ico` (ikon tab browser), dan `frontend/public/brand-lockup.png` (logo horizontal pada README). Semua aset berasal dari `logo.zip` yang disediakan pengguna.

## 1. Prasyarat

- **Python 3.10+** (disarankan Python 3.11 atau 3.12).
- **Node.js 18.18+** (atau Node.js 20/22 LTS) dan npm. Next.js 15 memerlukan paling sedikit Node.js 18.18.
- **ffmpeg** harus terpasang dan tersedia di `PATH` sistem.
- Koneksi internet untuk menginstal dependensi, mengunduh video YouTube, dan **mengunduh model Whisper pertama kali**. Setelah model di-cache, transkripsi file lokal dapat dilakukan secara offline.
- Video Downloader YouTube menggunakan Pytubefix dari `backend/requirements.txt`; pipeline transkripsi YouTube yang ada tetap memakai yt-dlp.
- Disarankan RAM minimal 8 GB. Model `medium` mengonsumsi RAM dan waktu CPU lebih banyak daripada `small`.
- Penyimpanan sementara yang cukup untuk file video dan hasil WAV. Batas upload default 2 GiB.

### Instalasi ffmpeg

- **Windows:** Jalankan `winget install Gyan.FFmpeg`, lalu tutup dan buka kembali terminal. Alternatif: unduh build dari https://ffmpeg.org/download.html dan masukkan folder `bin` ke variabel `PATH`.
- **macOS:** Jalankan `brew install ffmpeg` (jika Homebrew sudah terinstal).
- **Ubuntu/Debian Linux:** Jalankan `sudo apt update && sudo apt install -y ffmpeg`.

Cek instalasi: `ffmpeg -version` dan `ffprobe -version`.

## 2. Jalankan backend (FastAPI)

Buka terminal **di root proyek** `video-to-transcript/`, bukan di dalam `backend/`:

**Windows PowerShell:**

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Jika PowerShell memblokir aktivasi, gunakan `.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt` dan `.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000` tanpa aktivasi.

**macOS/Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Backend tersedia di `http://127.0.0.1:8000`. Dokumentasi REST API: `http://127.0.0.1:8000/docs`.

**Penting:** Jalankan **satu** proses Uvicorn saja (`--workers 1` jika memberi parameter worker), agar TimChao dan ClipUp berbagi antrean lokal yang sama. Job transkripsi menggunakan antrean FIFO dengan satu worker; job unduhan juga memakai satu worker tersendiri. Status dan hasil transkrip disimpan di `~/.video-to-transcript/job-state.sqlite3` (dapat diubah dengan `VTT_JOB_STATE_DB`). Job antrean dapat dilanjutkan sesudah restart jika inputnya masih tersedia; job yang sudah berjalan ditandai `interrupted` karena inferensi tidak dapat dilanjutkan dari titik sebelumnya. Unduhan aktif juga ditandai `interrupted`, tidak diulang otomatis.

## 3. Jalankan frontend (Next.js)

Di **terminal kedua**, dari root proyek:

```bash
cd frontend
npm install
npm run dev
```

Buka **http://127.0.0.1:3000** atau `http://localhost:3000` di browser.

Biarkan terminal backend dan frontend berjalan bersamaan. Tekan `Ctrl+C` pada masing-masing terminal untuk menghentikannya.

## 4. Cara menggunakan

1. Pilih tab **URL YouTube** dan tempel tautan, atau tab **Upload File** untuk memilih/drag-and-drop file.
2. Pilih model `small` (default, lebih cepat) atau `medium` (lebih akurat, tetapi lebih lambat).
3. Klik **Proses Video**. Lihat status download, ekstraksi audio, lalu transkripsi pada progress bar.
4. Saat selesai, klik **Copy to Clipboard** atau **Download as .txt**.

Format upload yang didukung: `.mp4`, `.mkv`, `.mov`, `.webm`, `.mp3`, `.wav`. Upload audio `.mp3`/`.wav` langsung diteruskan ke Whisper; video dan media YouTube diekstrak ke WAV mono 16 kHz menggunakan ffmpeg. Baris hasil berupa `[HH:MM:SS] teks`.

**Pertama kali dijalankan:** `faster-whisper` akan mengunduh model `small` atau `medium` secara otomatis dari Hugging Face. Ukuran unduhan cukup besar, terutama `medium`. Proses awal mungkin terlihat lama pada tahap transkripsi. Model yang telah diunduh disimpan di cache pengguna, bukan di dalam folder proyek.

## 5. Konfigurasi opsional

Konfigurasi backend melalui environment variables sebelum menjalankan Uvicorn:

| Variabel | Default | Keterangan |
|---|---|---|
| `VTT_MAX_UPLOAD_BYTES` | `2147483648` (2 GiB) | Batas ukuran file upload dan download |
| `VTT_FRONTEND_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | Daftar origin frontend untuk CORS |

Contoh PowerShell sebelum menjalankan backend:

```powershell
$env:VTT_MAX_UPLOAD_BYTES="1073741824"
```

Frontend dapat dikonfigurasi dengan menyalin `frontend/.env.local.example` menjadi `frontend/.env.local`:

```dotenv
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
NEXT_PUBLIC_MAX_UPLOAD_BYTES=2147483648
```

Jika batas ukuran backend diubah, **sesuaikan `NEXT_PUBLIC_MAX_UPLOAD_BYTES`** agar validasi frontend konsisten. Restart dev server setelah mengubah env frontend.

## 6. Endpoint backend

| Method | Endpoint | Fungsi |
|---|---|---|
| `POST` | `/api/process/url` | JSON `{"url":"https://youtu.be/...","model":"small"}`; mengembalikan `job_id` |
| `POST` | `/api/process/upload` | Multipart `file` + `model`; mengembalikan `job_id` |
| `GET` | `/api/status/{job_id}` | `status`, `progress` (0–100), `error_message` |
| `GET` | `/api/result/{job_id}` | Hasil `transcript` dan `filename_suggestion` saat status `done` |
| `GET` | `/api/jobs` dan `/api/jobs/{job_id}` | Daftar dan detail job termasuk stage, posisi antrean, dan worker availability |
| `GET` | `/api/worker/status` | Status worker transkripsi dan unduhan, job aktif, antrean FIFO |
| `POST` | `/api/jobs/{job_id}/cancel` | Batalkan job antrean atau minta pembatalan job aktif |

Downloader endpoints use the `/api/downloader` prefix. See [docs/VIDEO_DOWNLOADER_API.md](docs/VIDEO_DOWNLOADER_API.md) for inspection, download, status, validation, preview, history, cancellation, and transcript handoff routes.

Permintaan job baru masuk antrean dan mengembalikan `job_id`; client dapat memantau `/api/jobs`, `/api/status/{job_id}`, atau `/api/worker/status` tanpa mengirim ulang pekerjaan. Status meliputi `queued`, stage aktif, dan status terminal `done`, `error`, `cancelled`, atau `interrupted`. Progres transkripsi berbasis segmen dan merupakan **perkiraan**, bukan ETA. Hasil transkrip serta status disimpan lokal dalam SQLite; media input sementara dibersihkan setelah selesai/gagal.

### Kontrak worker untuk TimChao dan ClipUp

Kedua Clipper Agent harus memakai instance VTT lokal yang sama di `http://127.0.0.1:8000`. Sebelum mengirim pekerjaan baru, agent dapat membaca `GET /api/worker/status` dan `GET /api/jobs`; setelah menerima `job_id`, agent mem-poll status ID tersebut dan tidak mengirim ulang request hanya karena antrean sedang sibuk. Satu worker transkripsi memproses maksimum satu Whisper job pada satu waktu; job lain menunggu FIFO. Worker downloader memiliki antrean terpisah dengan konkurensi satu.

```json
{
  "transcription": {
    "pipeline": "transcription", "concurrency": 1,
    "worker_available": false,
    "active_job": {"job_id": "<uuid>", "status": "transcribing", "stage": "transcribing", "progress": 72, "queue_position": 0},
    "queue": [{"job_id": "<uuid>", "status": "queued", "stage": "extracting", "progress": 0, "queue_position": 1}],
    "queue_length": 1
  },
  "download": {"pipeline": "download", "concurrency": 1, "worker_available": true, "active_job": null, "queue": [], "queue_length": 0}
}
```

Kontrak request lama tetap berlaku: `/api/process/url` menerima `{"url":"https://youtu.be/<id>","model":"small"}`, `/api/process/upload` menerima multipart `file` + `model`, dan `/api/downloader/transcribe/{download_id}` menerima `{"model":"small"}`. Setiap route mengembalikan `job_id`; gunakan `/api/status/{job_id}` atau `/api/jobs/{job_id}` untuk stage/status, dan `POST /api/jobs/{job_id}/cancel` untuk pembatalan. Unduhan mengikuti inspect → download → `GET /api/downloader/status/{job_id}`; status antrean umum downloader ada di `GET /api/downloader/queue`. Rincian field dan contoh respons ada di [API contract](docs/VIDEO_DOWNLOADER_API.md). Perilaku runtime terbaru diverifikasi pada 28 Nov 2026; bukti dan batas uji dicatat di [QA record](docs/VIDEO_DOWNLOADER_QA.md).

## 7. Video Downloader

Buka halaman **Video Downloader** dari navigasi atas untuk memeriksa dan mengunduh file video langsung dari URL publik. File disimpan persisten di `downloads/YYYY-MM-DD/<job-id>/`; setiap hasil yang selesai memiliki `manifest.json`, metadata FFprobe, hasil full decode, dan SHA-256. File selesai tidak dihapus otomatis dan folder `downloads/` diabaikan Git.

Downloader mempertahankan byte sumber langsung tanpa transkode. Untuk URL file langsung, rincian codec, resolusi, FPS, durasi, dan bitrate bisa belum tersedia sampai file selesai diunduh dan diperiksa. Browser yang tidak mendukung codec tetap dapat mengunduh file asli.

Downloader mendukung YouTube melalui Pytubefix, HLS/DASH VOD statis yang tidak terenkripsi, direct media URL, Twitch Clips dengan token editor/broadcaster berizin, dan Google Drive melalui OAuth/API resmi. [Whop berstatus `SKIPPED_BY_OWNER`](docs/VIDEO_DOWNLOADER_SPEC.md). Fitur ini tidak menggunakan fallback yt-dlp; pipeline transkripsi YouTube tetap terpisah. Jangan gunakan URL ke konten yang tidak berhak Anda akses.

### Status UAT platform

| Platform | Status final |
|---|---|
| Direct HTTP(S) | PASS |
| YouTube | PASS |
| Google Drive | PASS |
| Twitch Clips | OPTIONAL — autentikasi dapat lulus; unduh dibatasi izin editor/broadcaster untuk channel target |
| HLS VOD | PASS |
| DASH VOD | PASS |
| Whop | SKIPPED_BY_OWNER |

**Production readiness:** PASS untuk workflow yang didukung. Twitch adalah fitur opsional dan pembatasan otorisasi target tidak menghalangi status produksi. Edge telah memutar preview URL direct MP4 sampai selesai dengan byte-range headers yang valid; detail bukti ada di [QA record](docs/VIDEO_DOWNLOADER_QA.md).

**Twitch:** autentikasi dan scope dapat berhasil, tetapi Clip tertentu hanya dapat diunduh melalui endpoint resmi saat pengguna token berwenang sebagai editor/broadcaster channel tersebut. Autentikasi saja tidak menjamin akses. Tidak ada fallback scraping pihak ketiga.

Untuk Google Drive, siapkan OAuth Desktop client di Google Cloud, set `VTT_GOOGLE_DRIVE_OAUTH_CLIENT_FILE`, lalu jalankan `python -m backend.downloader.google_drive_auth` dari root proyek. Browser akan meminta consent `drive.readonly`; lanjutkan di Google hanya jika setuju aplikasi lokal ini dapat membaca file Drive yang diizinkan akunmu. Token disimpan lokal di luar repo secara default.

Untuk Twitch Clips, daftarkan aplikasi Twitch dengan jenis public/device-code, set `VTT_TWITCH_CLIENT_ID`, lalu jalankan `python -m backend.downloader.twitch_auth` dari root proyek. Device Code Flow resmi meminta scope `editor:manage:clips`; selesaikan kode dan consent di Twitch menggunakan akun editor/broadcaster yang berwenang. Access/refresh token ditulis ke `~/.video-to-transcript/twitch-token.json` dan diperbarui otomatis; jangan bagikan atau commit file tersebut. `VTT_TWITCH_ACCESS_TOKEN` tetap tersedia untuk konfigurasi token manual.

HLS/DASH hanya menerima VOD publik tanpa DRM/enkripsi; live stream dan format manifest yang belum didukung akan ditolak. Adapter menyalin media dan melakukan mux Matroska tanpa re-encoding.

### Menjalankan layanan dengan `vtt-activate`

Pada PowerShell yang memiliki function VTT di `$PROFILE`, jalankan:

```powershell
. $PROFILE
vtt-activate
```

Function ini membuka tab Windows Terminal untuk backend di `127.0.0.1:8000` dan frontend di `localhost:3000`. Buka `http://127.0.0.1:3000`. Jika startup melaporkan port sedang digunakan, periksa pemilik port sebelum menghentikan proses apa pun. API lokal tidak memiliki autentikasi; jangan expose ke LAN/internet.

### VTT sebagai penyedia video/transkrip untuk external Clipper Agent

VTT dapat menyediakan sumber video asli dan metadata terverifikasi kepada Clipper Agent terpisah yang berjalan pada komputer yang sama. Agent memakai API `POST /api/downloader/inspect`, `POST /api/downloader/download`, `GET /api/downloader/status/{job_id}`, dan `GET /api/downloader/result/{job_id}`. Result berisi `file_url`, `preview_url`, metadata FFprobe, hasil full decode, serta SHA-256; file tersimpan di `downloads/YYYY-MM-DD/<job_id>/`. Setelah Agent membuat clip, ia dapat meminta transkrip melalui `POST /api/downloader/transcribe/{download_id}` lalu memakai API status/result transcription. Lihat contoh lengkap dan JSON di [API contract](docs/VIDEO_DOWNLOADER_API.md).

Integrasi ini menggunakan API localhost tanpa autentikasi dan tidak memberi Agent akses jarak jauh. Jangan membuka port API ke jaringan. Gunakan hanya sumber yang Anda berhak akses.

Pengaturan opsional backend (environment variables saat menjalankan dari root proyek):

| Variabel | Default | Keterangan |
|---|---:|---|
| `VTT_DOWNLOAD_DIR` | `downloads` | Lokasi media dan manifest; relative path dihitung dari working directory proses backend |
| `VTT_DOWNLOAD_MAX_BYTES` | `10737418240` | Batas ukuran unduhan (10 GiB) |
| `VTT_DOWNLOAD_INSPECTION_TTL` | `900` | Masa berlaku hasil inspeksi (detik) |
| `VTT_JOB_STATE_DB` | `~/.video-to-transcript/job-state.sqlite3` | Lokasi SQLite untuk status, antrean, dan hasil transkrip |
| `VTT_TWITCH_CLIENT_ID` | — | Twitch application Client ID untuk Clip API |
| `VTT_TWITCH_ACCESS_TOKEN` | — | Twitch User Access Token untuk editor/broadcaster berwenang |
| `VTT_TWITCH_TOKEN_FILE` | `~/.video-to-transcript/twitch-token.json` | Access/refresh token Twitch lokal dari Device Code Flow |
| `VTT_GOOGLE_DRIVE_OAUTH_CLIENT_FILE` | — | Lokasi file OAuth Desktop client JSON |
| `VTT_GOOGLE_DRIVE_TOKEN_FILE` | `~/.video-to-transcript/google-drive-token.json` | Lokasi token OAuth lokal |

Dependensi downloader terdaftar dalam `backend/requirements.txt`; `ffmpeg` dan `ffprobe` harus tersedia di `PATH` untuk mux dan validasi hasil.

## 8. Test

Dari root, setelah instalasi dependensi backend dan dev:

```bash
pip install -r backend/requirements-dev.txt
python -m pytest backend/tests -q
```

Tes inti downloader yang offline juga dapat dijalankan tanpa pytest:

```powershell
.\backend\.venv\Scripts\python.exe -m unittest discover -s backend\tests -p test_downloader.py -v
```

Tes API berjalan offline dengan mock ekstraksi dan transkripsi; **tidak** mengukur kualitas model asli. Periksa tipe frontend dengan:

```bash
cd frontend
npm run typecheck
npm run build
```

### Uji manual yang direkomendasikan

- Upload sampel audio `.wav` dan video `.mp4`, lalu pastikan baris bertimestamp, copy dan download bekerja.
- Coba URL YouTube publik yang boleh diunduh, dengan durasi pendek, lalu video ±10 menit.
- Coba URL salah, video private, file berekstensi tidak didukung, dan file melampaui batas.
- Kirim dua permintaan job dari client berbeda; pastikan job kedua mendapat posisi FIFO dan worker hanya memproses satu job.
- Periksa `/api/worker/status`, batalkan job antrean dan job aktif, lalu pastikan worker tersedia kembali dan status terminal sesuai.
- Restart backend hanya saat tidak ada pekerjaan aktif; pastikan queued job yang input-nya tersedia dilanjutkan dan job terinterupsi dilaporkan eksplisit.

**Catatan:** Pengujian end-to-end dengan Whisper asli dan YouTube membutuhkan model, file media nyata, dan koneksi internet; tes otomatis offline tidak menggantikannya. Kinerja pada Ryzen 7 5825U CPU-only sangat bergantung pada durasi dan kualitas audio.

## 9. Struktur proyek

```text
video-to-transcript/
├── backend/
│   ├── main.py
│   ├── jobs.py
│   ├── downloader/
│   │   ├── adapters/
│   │   ├── jobs.py
│   │   ├── router.py
│   │   ├── security.py
│   │   ├── storage.py
│   │   └── validator.py
│   ├── pipeline/
│   │   ├── downloader.py
│   │   ├── extractor.py
│   │   ├── transcriber.py
│   │   └── formatter.py
│   ├── tests/
│   └── requirements.txt
├── frontend/
│   ├── app/
│   ├── components/
│   ├── lib/
│   ├── public/
│   │   ├── logo.webp
│   │   ├── favicon.ico
│   │   └── brand-lockup.png
│   └── package.json
├── docs/
│   ├── CONTEXT.md
│   ├── PRD.md
│   ├── SPEC.md
│   ├── ARCHITECTURE.md
│   ├── DESIGN.md
│   ├── WORKFLOW.md
│   ├── VIDEO_DOWNLOADER_SPEC.md
│   ├── VIDEO_DOWNLOADER_ARCHITECTURE.md
│   ├── VIDEO_DOWNLOADER_API.md
│   ├── VIDEO_DOWNLOADER_WORKFLOW.md
│   └── VIDEO_DOWNLOADER_QA.md
├── LICENSE
└── README.md
```

Lisensi: **MIT**, copyright (c) 2026 Alfiz.
