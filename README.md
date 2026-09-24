# Meja Pantau

Halaman pemantauan pribadi untuk IHSG, makro, dan kalender acara penting. Berjalan gratis di GitHub, tanpa server dan tanpa langganan apa pun.

- **Halaman:** `index.html`, ditampilkan oleh GitHub Pages.
- **Harga otomatis:** GitHub Actions menjalankan `scripts/update_market.py` Senin–Jumat pukul 07.30, 12.30, 16.30, dan 20.30 WIB. Harga diambil dari Yahoo Finance lalu disimpan ke `data/market.json`.
- **Data yang kamu isi sendiri:** `data/manual.json` (BI Rate, suku bunga The Fed, net asing, timah, batu bara, dan dua centang) dan `data/agenda.json` (kalender).

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
| Ubah BI Rate, suku bunga The Fed, net asing, timah, batu bara | **Ubah data** → isi di kartunya → **Simpan ke GitHub** |
| Lihat acara di tanggal tertentu | Klik tanggalnya di kalender. Detailnya muncul di kotak kanan. |
| Tambah acara ke kalender | **Ubah data** → klik tanggalnya → isi form di bawah kalender → **Simpan ke GitHub** |

Kalau belum sempat klik simpan, perubahan disimpan sementara di browser dan muncul lagi saat halaman dibuka.

**Tanpa token:** klik **Unduh file**, lalu di GitHub buka folder `data/` → **Add file → Upload files** → unggah file itu (timpa yang lama).

### Kapan mengisi data manual
- **BI Rate:** setelah setiap RDG BI (tanggalnya ada di kalender)
- **Suku bunga The Fed:** setelah setiap rapat FOMC
- **Net asing:** setiap akhir pekan (sumber: berita pasar atau aplikasi sekuritas)
- **Timah & batu bara:** kapan saja, misalnya seminggu sekali (tradingeconomics.com)
- **Kalender:** jadwal The Fed dan BI untuk tahun berikutnya biasanya terbit sekitar Desember. Tambahkan sekali setahun.

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
scripts/update_market.py         pengambil harga
.github/workflows/update-market.yml   jadwal otomatis
```
