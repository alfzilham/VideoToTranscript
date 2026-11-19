# WORKFLOW.md — Video to Transcript

## 1. Alur Pengembangan (Development Workflow)

### Tahap 1 — Setup Dasar
1. Inisialisasi repo GitHub (lisensi open source, misal MIT).
2. Setup struktur folder `backend/` dan `frontend/` sesuai ARCHITECTURE.md.
3. Setup `requirements.txt` (backend) dan `package.json` (frontend).
4. Pastikan `ffmpeg` terinstall di sistem (dicek di README, bukan dependency Python).

### Tahap 2 — Backend Pipeline (Core Logic Dulu, Tanpa UI)
1. Implementasi `downloader.py` — wrapper `yt-dlp`, test download manual dari URL.
2. Implementasi `extractor.py` — wrapper `ffmpeg`, test ekstraksi audio dari file video.
3. Implementasi `transcriber.py` — wrapper `faster-whisper`, test transkripsi dari file `.wav`.
4. Implementasi `formatter.py` — ubah output segmen jadi teks timestamp.
5. Test end-to-end pipeline manual lewat script/CLI dulu (belum lewat API) untuk pastikan core logic benar.

### Tahap 3 — Backend API (FastAPI)
1. Implementasi `jobs.py` — job state management in-memory.
2. Implementasi endpoint `POST /api/process/url`.
3. Implementasi endpoint `POST /api/process/upload`.
4. Implementasi endpoint `GET /api/status/{job_id}`.
5. Implementasi endpoint `GET /api/result/{job_id}`.
6. Test semua endpoint manual (Postman/curl/Thunder Client).

### Tahap 4 — Frontend (Next.js)
1. Setup halaman utama (`page.tsx`) dengan layout dasar sesuai DESIGN.md.
2. Implementasi komponen `InputForm` (tab URL/Upload).
3. Implementasi komponen `ProgressIndicator` (polling ke backend).
4. Implementasi komponen `TranscriptResult` (tampilan hasil + tombol copy/download).
5. Hubungkan ke backend API (fetch calls).

### Tahap 5 — Integrasi & Testing End-to-End
1. Test alur lengkap: paste URL → download → extract → transcribe → tampil di UI → copy/download.
2. Test alur upload file.
3. Test error handling (URL invalid, file terlalu besar, video private, dll).
4. Test dengan video durasi bervariasi (pendek ~2 menit, sedang ~10 menit) untuk cek waktu proses realistis di CPU.

### Tahap 6 — Dokumentasi & Open Source Readiness
1. Tulis `README.md` — instruksi instalasi, requirement sistem (`ffmpeg`, Python, Node.js), cara menjalankan backend & frontend, disclaimer penggunaan personal.
2. Tambahkan `LICENSE` (misal MIT).
3. Review ulang 6 file dokumentasi (`SPEC.md`, `ARCHITECTURE.md`, `DESIGN.md`, `CONTEXT.md`, `PRD.md`, `WORKFLOW.md`) agar konsisten dengan implementasi akhir.
4. Push ke GitHub sebagai repo publik.

## 2. Urutan Prioritas Pengerjaan

Core pipeline (Tahap 2) dikerjakan **sebelum** API dan UI, supaya bagian paling berisiko gagal (integrasi `yt-dlp` + `ffmpeg` + `faster-whisper` di CPU) divalidasi lebih dulu tanpa terbebani kompleksitas API/UI.

## 3. Checklist Definisi "Selesai" (Definition of Done) per Fitur

- [ ] Kode berjalan tanpa error di kondisi normal.
- [ ] Error handling dasar sudah ada (tidak crash saat input tidak valid).
- [ ] Sudah ditest manual minimal 1 kali dengan video nyata.
- [ ] Tidak meninggalkan file temporary menumpuk di disk setelah job selesai.

## 4. Catatan Pengembangan Lanjutan (Future, Belum untuk v1)

- Dukungan antrian job paralel (jika suatu saat dipakai lebih dari 1 user).
- Dockerize aplikasi agar lebih mudah di-setup oleh kontributor open source.
- Opsi pemilihan bahasa transkripsi secara eksplisit di UI.
- Opsi ringkasan otomatis (integrasi langsung ke AI API) — saat ini sengaja dipisah, transcript mentah saja yang jadi scope v1.
