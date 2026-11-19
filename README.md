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

**Penting:** Jalankan **satu** proses Uvicorn saja (`--workers 1` jika memberi parameter worker). Job disimpan di RAM proses, sehingga `--reload`/restart akan menghapus status dan hasil job sebelumnya. Jangan mulai job baru sebelum job aktif selesai.

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

Hanya satu job boleh aktif. Permintaan baru ketika job masih berjalan mendapat respons HTTP `409`. Progres transkripsi berbasis segmen dan merupakan **perkiraan**, bukan ETA. Hasil tersimpan di memori sampai server backend dihentikan; media sementara dibersihkan otomatis setelah selesai/gagal.

## 7. Test

Dari root, setelah instalasi dependensi backend:

```bash
pip install pytest httpx
python -m pytest backend/tests -q
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
- Jika sedang ada job aktif, periksa bahwa permintaan job lain ditolak dan folder sementara telah dibersihkan.

**Catatan:** Pengujian end-to-end dengan Whisper asli dan YouTube membutuhkan model, file media nyata, dan koneksi internet; tes otomatis offline tidak menggantikannya. Kinerja pada Ryzen 7 5825U CPU-only sangat bergantung pada durasi dan kualitas audio.

## 8. Struktur proyek

```text
video-to-transcript/
├── backend/
│   ├── main.py
│   ├── jobs.py
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
│   └── WORKFLOW.md
├── LICENSE
└── README.md
```

Lisensi: **MIT**, copyright (c) 2026 Alfiz.
