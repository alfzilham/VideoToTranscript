# PRD.md — Video to Transcript

## 1. Ringkasan Produk

Video to Transcript adalah aplikasi web lokal yang mengubah video (dari URL YouTube atau file upload) menjadi transcript teks bertimestamp, yang dapat disalin dan digunakan sebagai konteks untuk AI berbasis teks.

## 2. Tujuan

- Menyediakan cara cepat untuk mendapatkan transcript bertimestamp dari video apa pun.
- Menghasilkan output yang langsung siap pakai (copy-paste) sebagai konteks percakapan dengan AI.
- Berjalan sepenuhnya lokal tanpa ketergantungan pada layanan berbayar (opsional, bisa pakai API jika diinginkan di masa depan).

## 3. Target Pengguna

- Pembuat aplikasi ini sendiri (penggunaan personal).
- Siapa pun yang clone repo open source ini dan menjalankannya secara lokal.

## 4. User Stories

| # | Sebagai pengguna, saya ingin... | Agar... |
|---|---|---|
| 1 | Menempelkan URL YouTube | Sistem otomatis mengunduh dan memproses video tersebut |
| 2 | Mengupload file video langsung | Saya bisa memproses video yang tidak ada di YouTube |
| 3 | Melihat progres pemrosesan (download → extract audio → transkripsi) | Saya tahu sistem sedang bekerja dan tidak macet |
| 4 | Mendapatkan transcript dengan timestamp per segmen | Saya bisa memberi AI konteks waktu kejadian dalam video |
| 5 | Menyalin hasil transcript dengan satu klik | Saya bisa langsung tempel ke AI tanpa edit manual |
| 6 | Mengunduh transcript sebagai file .txt | Saya bisa menyimpan hasilnya untuk dipakai lagi nanti |
| 7 | Memilih model Whisper (small/medium) | Saya bisa menyeimbangkan kecepatan vs akurasi sesuai kebutuhan |

## 5. Fitur (Scope v1)

### Harus Ada (Must Have)
- Input URL YouTube → download otomatis via `yt-dlp`.
- Input upload file video (mp4, mkv, dll).
- Ekstraksi audio dari video via `ffmpeg`.
- Transkripsi audio ke teks bertimestamp via `faster-whisper` (model `small` default).
- Tampilan hasil transcript di UI dengan format: `[00:00:02] teks ucapan...`.
- Tombol "Copy to Clipboard".
- Tombol "Download as .txt".

### Bagus Jika Ada (Should Have)
- Pilihan model Whisper (`small` / `medium`) dari UI.
- Indikator progres per tahap (downloading, extracting, transcribing).
- Riwayat transcript yang pernah dibuat (disimpan lokal di folder output).

### Tidak Termasuk Scope v1 (Out of Scope)
- Autentikasi/login.
- Multi-user / multi-session paralel.
- Deployment ke cloud/server publik.
- Dukungan GPU/CUDA.
- Ringkasan otomatis oleh AI (hanya transcript mentah, ringkasan dilakukan oleh AI eksternal setelah transcript ditempel).
- Dukungan bahasa selain yang didukung Whisper secara default (multi-bahasa tetap didukung karena Whisper multilingual, tapi tidak ada UI khusus pemilihan bahasa di v1).

## 6. Kriteria Sukses

- Video 10 menit dapat diproses end-to-end (download/upload → transcript) tanpa error di laptop pengguna (Ryzen 7 5825U, 16GB RAM, CPU-only).
- Hasil transcript cukup akurat untuk dipahami AI sebagai konteks (tidak perlu 100% sempurna, cukup dapat dipahami).
- Setup dari clone repo hingga aplikasi jalan di localhost tidak lebih dari 15 menit mengikuti README.

## 7. Batasan Teknis yang Diketahui

- Tidak ada GPU NVIDIA/CUDA tersedia → transkripsi berjalan di CPU, lebih lambat dari realtime untuk model besar.
- Ukuran file upload dibatasi oleh storage lokal laptop pengguna.
- Akurasi transkripsi bergantung pada kualitas audio asli video.
