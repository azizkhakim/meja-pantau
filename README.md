# Meja Pantau

Halaman pemantauan pribadi untuk IHSG, makro, dan kalender acara penting. Berjalan gratis di GitHub, tanpa server dan tanpa langganan apa pun.

- **Halaman:** `index.html`, ditampilkan oleh GitHub Pages.
- **Harga otomatis:** GitHub Actions menjalankan `scripts/update_market.py` Senin–Jumat pukul 07.30, 12.30, 16.30, dan 20.30 WIB. Harga diambil dari Yahoo Finance lalu disimpan ke `data/market.json`.
- **Data yang kamu isi sendiri:** `data/manual.json` (BI Rate, suku bunga The Fed, net asing, timah, batu bara, CPO, dan dua centang) dan `data/agenda.json` (kalender).

Bukan rekomendasi jual atau beli. Keputusan dan risikonya tetap di tanganmu.

---

## Pemasangan pertama (sekali saja, ±15 menit)

### 1. Buat repository
1. Buka https://github.com/new
2. Isi **Repository name**: `meja-pantau`
3. Pilih **Public** (GitHub Pages gratis hanya untuk repo publik)
4. Jangan centang README, .gitignore, atau license. Repo harus kosong.
5. Klik **Create repository**

### 2. Buat token
Token dipakai untuk mengunggah kode pertama kali, dan nanti untuk menyimpan perubahan dari halaman.

1. Buka https://github.com/settings/personal-access-tokens/new
2. **Token name**: `meja-pantau`
3. **Expiration**: pilih yang paling lama. Kalau nanti kedaluwarsa, cukup buat token baru dengan cara yang sama.
4. **Repository access**: *Only select repositories* → pilih `meja-pantau`
5. **Permissions → Repository permissions**, atur tiga ini ke **Read and write**:
   - **Contents**
   - **Actions**
   - **Workflows**
6. Klik **Generate token**, lalu salin token yang diawali `github_pat_...`. Token hanya ditampilkan sekali. Simpan di tempat aman, misalnya aplikasi catatan yang terkunci.

### 3. Unggah kode
Di Terminal, di folder ini:

```bash
git remote add origin https://github.com/USERNAME/meja-pantau.git
git push -u origin main
```

Saat diminta **Username**, isi username GitHub-mu. Saat diminta **Password**, tempel **token** (bukan password GitHub). Di macOS, kredensial ini disimpan di Keychain, jadi tidak perlu diisi lagi.

### 4. Nyalakan GitHub Pages
1. Di repo: **Settings → Pages**
2. **Source**: *Deploy from a branch*
3. **Branch**: `main`, folder `/ (root)` → **Save**
4. Tunggu 1–2 menit. Alamat halamanmu: `https://USERNAME.github.io/meja-pantau/`

### 5. Cek pembaruan otomatis
1. Di repo: **Actions → Perbarui data pasar → Run workflow**
2. Setelah selesai (centang hijau), `data/market.json` berisi harga terbaru.

Kalau langkah ini gagal dengan pesan izin, buka **Settings → Actions → General → Workflow permissions**, pilih **Read and write permissions**, lalu klik **Save**.

### 6. Hubungkan halaman ke GitHub (di setiap perangkat)
1. Buka halamanmu dan gulir ke **Pengaturan penyimpanan GitHub**
2. Pemilik dan nama repo biasanya terisi otomatis. Tempel token, lalu klik **Simpan pengaturan** dan **Tes koneksi**.
3. Setelah terhubung, tombol **Perbarui harga sekarang** muncul di atas, dan **Simpan ke GitHub** bisa dipakai.

> Token tersimpan di browser perangkat itu. Jangan isi token di komputer umum atau milik orang lain.

---

## Pemakaian sehari-hari

| Mau apa | Caranya |
|---|---|
| Lihat kondisi pasar | Buka halaman. Harga otomatis diperbarui 4× sehari pada hari kerja. |
| Harga terbaru sekarang juga | Tombol **Perbarui harga sekarang**, tunggu 2–3 menit, lalu muat ulang halaman |
| Ubah BI Rate, suku bunga The Fed, net asing, timah, batu bara, CPO | **Ubah data** → isi di kartunya → **Simpan ke GitHub** |
| Lihat acara di tanggal tertentu | Klik tanggalnya di kalender. Detailnya muncul di kotak kanan. |
| Tambah acara ke kalender | **Ubah data** → klik tanggalnya → isi form di bawah kalender → **Simpan ke GitHub** |

Kalau belum sempat klik simpan, perubahan disimpan sementara di browser dan muncul lagi saat halaman dibuka.

**Tanpa token:** klik **Unduh file**, lalu di GitHub buka folder `data/` → **Add file → Upload files** → unggah file itu (timpa yang lama).

### Kapan mengisi data manual
- **BI Rate:** setelah setiap RDG BI (tanggalnya ada di kalender)
- **Suku bunga The Fed:** setelah setiap rapat FOMC
- **Net asing:** setiap akhir pekan (sumber: berita pasar atau aplikasi sekuritas)
- **Timah, batu bara & CPO:** kapan saja, misalnya seminggu sekali (tradingeconomics.com). CPO dalam ringgit per ton (RM/t), kontrak acuan Bursa Malaysia.
- **Kalender:** jadwal The Fed dan BI untuk tahun berikutnya biasanya terbit sekitar Desember. Tambahkan sekali setahun.

---

## Saham layak dipantau: cara kerja & rapor

- **Peta keterkaitan** (`data/peta.json`): tema (emas, batu bara, sawit, dan lainnya), saham anggotanya, aturan kapan tema aktif, dan skenario tiap acara. Tambah atau hapus kode saham di sini.
- **Level teknikal** dihitung robot 4× sehari (`scripts/update_market.py`, fungsi `setup_teknikal`). Kandidat hanya muncul kalau: tren naik dengan MA50 menanjak, lebih kuat dari IHSG dalam 60 hari, harga kembali dekat MA20, RSI < 75, cut loss ≤ 9%, transaksi ≥ Rp5 miliar/hari, **dan IHSG di atas MA50**.
- **Rencana keluar:** jual separuh di TP1 lalu pindahkan cut loss ke harga beli, sisanya di TP2. Tutup setelah 20 hari bursa.
- **Rapor aturan (backtest)**: `scripts/backtest.py` menguji aturan yang sama pada data 2 tahun. Jalan otomatis setiap Sabtu pagi. Hasilnya tampil di halaman. Aturan tanpa filter IHSG dan kekuatan relatif terbukti rugi, jadi jangan dilonggarkan tanpa menguji ulang.
- **Jurnal sinyal** (`data/jurnal.json`): setiap kandidat yang lolos semua syarat dicatat otomatis, lalu statusnya diikuti sampai selesai. Ini rapor nyata dari waktu ke waktu.

Menguji perubahan aturan sendiri: ubah angka di bagian atas `scripts/update_market.py`, lalu jalankan `python3 scripts/backtest.py` dan bandingkan hasilnya sebelum dikirim.

---

## Notifikasi Telegram (gratis, sekali atur ±5 menit)

Robot mengirim pesan saat: ada kandidat baru, order terisi, TP1/TP2 atau cut loss tersentuh, IHSG naik/turun melewati MA50, dan pagi hari sebelum acara berdampak tinggi (H-1 dan hari-H).

1. Di Telegram, buka **@BotFather** → kirim `/newbot` → beri nama, misalnya `Meja Pantau Aziz`, dan username yang berakhiran `bot`. Salin **token** yang diberikan (bentuknya `123456789:AA...`).
2. Buka bot barumu dan kirim pesan apa saja, misalnya `halo`.
3. Buka di browser: `https://api.telegram.org/botTOKEN/getUpdates` (ganti `TOKEN`). Cari `"chat":{"id":` lalu salin angkanya. Itu **chat ID**.
4. Di repo GitHub: **Settings → Secrets and variables → Actions → New repository secret**, buat dua secret:
   - `TELEGRAM_TOKEN` = token dari langkah 1
   - `TELEGRAM_CHAT_ID` = angka dari langkah 3
5. Tes: **Actions → Perbarui data pasar → Run workflow**. Pesan hanya dikirim kalau ada kejadian baru, jadi tidak ada pesan juga normal.

Secret tidak ikut terlihat di repo publik.

---

## Kalau ada masalah

| Gejala | Penyebab & solusi |
|---|---|
| Harga tidak berubah berhari-hari, ada tanda "data lama" | Buka tab **Actions**. Kalau ada tanda silang merah, klik untuk melihat pesannya. Kalau muncul *"This scheduled workflow is disabled"*, klik **Enable workflow**. GitHub mematikan jadwal otomatis kalau repo publik tidak ada aktivitas 60 hari. |
| Semua harga gagal ("gagal" di log Actions) | Yahoo Finance mungkin mengubah cara aksesnya. Data lama tetap tampil. Periksa `scripts/update_market.py`, bagian `URL`. |
| "Token ditolak (401)" | Token kedaluwarsa. Buat token baru (langkah 2) lalu tempel lagi di pengaturan halaman. |
| "Akses ditolak (403/404)" | Token belum punya izin Contents/Actions **Read and write**, atau dibuat untuk repo lain. |
| Halaman kosong saat dibuka dari file | Buka lewat alamat GitHub Pages, atau jalankan `python3 -m http.server` di folder ini lalu buka http://localhost:8000 |

---

## Mengubah aturan pemaknaan
Semua ambang ada di `index.html`, di daftar `IND` bagian atas kode. Contoh kartu emas:

```js
{key:"emas", ..., t:[4260,4440], hi:"good", ...
 text:{bad:"Di bawah 4.260: ...", mid:"...", good:"Tembus 4.440: ..."}}
```

- `t: [bawah, atas]`: batas zona
- `hi: "good"`: makin tinggi makin baik. `hi: "bad"`: makin tinggi makin buruk.
- `text`: kalimat pemaknaan untuk tiap zona

Ubah angkanya di GitHub (buka file → ikon pensil → **Commit changes**). Halaman terbarui dalam ±1 menit.

## Menambah indikator otomatis
Di `scripts/update_market.py`, tambahkan baris di `INDIKATOR` (kunci → simbol Yahoo Finance, misalnya `"perak": "SI=F"`). Lalu tambahkan kartunya di daftar `IND` di `index.html` dengan `auto:true` dan kunci yang sama.

## Struktur folder
```
index.html                       halaman
data/market.json                 harga otomatis (jangan diedit manual)
data/manual.json                 indikator manual + centang
data/agenda.json                 kalender
data/peta.json                   peta tema, indikator, acara → saham
data/sinyal.json                 level teknikal tiap saham (otomatis)
data/jurnal.json                 jurnal sinyal (otomatis)
data/backtest.json               rapor aturan (otomatis tiap Sabtu)
data/notif.json                  catatan notifikasi terkirim (otomatis)
scripts/backtest.py              uji aturan pada data 2 tahun
scripts/update_market.py         pengambil harga
.github/workflows/update-market.yml   jadwal otomatis
```
