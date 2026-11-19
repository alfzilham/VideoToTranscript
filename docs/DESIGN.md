# DESIGN.md — Video to Transcript

## 1. Prinsip Desain

- Sederhana dan fungsional — ini tool personal, bukan produk konsumen, jadi prioritas adalah kejelasan dan kecepatan penggunaan, bukan estetika kompleks.
- Single page, tanpa navigasi berlapis.
- Feedback visual jelas di setiap tahap proses (user harus selalu tahu sistem sedang apa).

## 2. Struktur Halaman (Single Page)

```
┌──────────────────────────────────────────────┐
│  Video to Transcript                          │
├──────────────────────────────────────────────┤
│  [Tab: URL YouTube] [Tab: Upload File]        │
│                                                │
│  ┌──────────────────────────────────────┐    │
│  │ (input field sesuai tab aktif)        │    │
│  └──────────────────────────────────────┘    │
│                                                │
│  Model Whisper: [Dropdown: small ▾]           │
│                                                │
│  [ Proses Video ]                             │
│                                                │
│  ──────────────────────────────────────────  │
│  Status: Mengekstrak audio... (45%)           │
│  ──────────────────────────────────────────  │
│                                                │
│  Hasil Transcript:                            │
│  ┌──────────────────────────────────────┐    │
│  │ [00:00:02] Teks ucapan pertama...     │    │
│  │ [00:00:08] Lanjutan ucapan...         │    │
│  │ ...                                    │    │
│  └──────────────────────────────────────┘    │
│                                                │
│  [ Copy to Clipboard ]  [ Download .txt ]     │
└──────────────────────────────────────────────┘
```

## 3. Komponen UI

### 3.1 Tab Switcher (URL / Upload)
- Dua tab sederhana untuk berpindah mode input.
- Tab aktif ditandai dengan garis bawah atau latar lebih gelap (bukan warna sebagai satu-satunya penanda, agar tetap jelas dalam mode hitam-putih).

### 3.2 Input Field
- **Mode URL:** single text input, placeholder `https://youtube.com/watch?v=...`
- **Mode Upload:** drag-and-drop area dengan border putus-putus + teks "Klik atau drag file video/audio di sini", menampilkan nama file setelah dipilih.

### 3.3 Dropdown Model Whisper
- Opsi: `small (cepat)`, `medium (lebih akurat, lebih lambat)`.
- Default: `small`.

### 3.4 Tombol Proses
- Disabled saat input kosong atau sedang memproses job lain.
- Label berubah jadi "Memproses..." saat job berjalan.

### 3.5 Progress Indicator
- Teks status tahap saat ini: `Mengunduh video...` → `Mengekstrak audio...` → `Mentranskripsi...` → `Selesai`.
- Progress bar sederhana (persentase), diupdate dari polling endpoint status.
- Jika error: tampilkan pesan error dengan ikon peringatan (bukan warna merah saja — tambahkan simbol teks "[!]" agar tetap jelas tanpa warna).

### 3.6 Area Hasil Transcript
- Textarea atau `<pre>` block, scrollable, monospace font agar timestamp sejajar rapi.
- Baris timestamp dalam kurung siku `[HH:MM:SS]` diikuti teks ucapan.

### 3.7 Tombol Aksi Hasil
- **Copy to Clipboard** — feedback singkat "Tersalin!" setelah diklik.
- **Download .txt** — langsung trigger download file.

## 4. Gaya Visual

- **Font:** Arial (sesuai preferensi default dokumen), monospace khusus untuk area transcript agar timestamp rapi.
- **Skema warna:** monochrome-friendly — hitam, putih, abu-abu. Tidak ada elemen yang bergantung pada warna saja untuk menyampaikan makna (status error pakai simbol + teks, bukan cuma warna merah).
- **Layout:** center-aligned, max-width terbatas (misal 800px) agar nyaman dibaca di layar lebar maupun sempit.
- **Spacing:** cukup lega antar elemen agar tidak terasa padat.

## 5. Responsif

- Karena hanya dipakai di laptop sendiri (localhost), prioritas desktop-first.
- Tetap usahakan layout tidak rusak di ukuran layar lebih kecil (laptop kamu: 1920x1200), tidak perlu optimasi mobile khusus di v1.

## 6. Aksesibilitas Dasar

- Kontras teks-background cukup tinggi (hitam di atas putih) agar aman dibaca di mode hitam-putih/print jika suatu saat dicetak.
- Label jelas di setiap input (tidak hanya placeholder).


## Aset Brand (Implementasi)

- Logo-mark WEBP: `frontend/public/logo.webp`, ditampilkan pada header utama.
- Favicon ICO: `frontend/public/favicon.ico`, direferensikan dalam metadata Next.js.
- Logo-lockup PNG: `frontend/public/brand-lockup.png`, ditampilkan di `README.md`.
