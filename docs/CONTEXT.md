# CONTEXT.md — Video to Transcript

## Latar Belakang

AI berbasis teks (seperti ChatGPT, Claude, dll) tidak dapat "menonton" video secara langsung. Ketika seseorang ingin mendiskusikan isi sebuah video YouTube dengan AI — misalnya meminta ringkasan, analisis, atau tanya jawab seputar konten video tersebut — AI tidak punya cara untuk memahami apa yang terjadi di dalam video kecuali diberikan representasi teksnya.

**Video to Transcript** lahir dari kebutuhan personal untuk menjembatani gap ini: mengubah video (dari YouTube atau file lokal) menjadi transcript bertimestamp yang bisa langsung ditempel sebagai konteks ke AI.

## Masalah yang Diselesaikan

1. AI tidak bisa membaca/menonton video secara native.
2. Caption YouTube otomatis tidak selalu tersedia, kurang akurat, atau sulit diekspor dalam format yang rapi.
3. Video yang diupload sendiri (rekaman pribadi, materi kuliah, dll) sama sekali tidak punya transcript.
4. Dibutuhkan format output yang konsisten (timestamp + teks) agar AI dapat memahami urutan dan konteks waktu kejadian dalam video.

## Siapa yang Menggunakan

- Hanya digunakan oleh pembuatnya sendiri (Alfiz) untuk kebutuhan pribadi.
- Dijalankan secara lokal di laptop (localhost), tidak di-deploy ke server publik.
- Tidak ada multi-user, tidak ada autentikasi, tidak ada biaya hosting.

## Mengapa Open Source

Meskipun hanya dipakai sendiri, proyek ini dipublikasikan sebagai open source di GitHub agar:
- Bisa menjadi portofolio teknis (fullstack + integrasi AI/speech-to-text).
- Orang lain dengan kebutuhan serupa bisa clone dan menjalankan versinya sendiri secara lokal.
- Tidak ada instance publik yang di-host atau dikelola oleh pembuat — tanggung jawab deployment ada di tangan masing-masing pengguna yang clone repo.

## Batasan yang Disengaja

- Tidak ada rencana untuk mendukung multi-user atau deployment cloud dalam skala besar.
- Tidak ada SLA, tidak ada dukungan GPU (laptop pengguna menggunakan AMD Radeon integrated, tanpa CUDA, sehingga Whisper berjalan di CPU).
- Prioritas: kesederhanaan setup dan kejelasan output teks, bukan skalabilitas atau performa maksimal.
