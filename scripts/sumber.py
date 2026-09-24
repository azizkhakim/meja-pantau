"""Pengambil data dari situs publik (tanpa API berbayar) untuk indikator dan kalender.

Setiap fungsi mengembalikan None / daftar kosong kalau gagal, supaya robot tetap jalan
dan nilai lama dipakai. Situs bisa mengubah tampilannya; kalau satu sumber rusak,
perbaiki fungsi yang bersangkutan saja.
"""

import html
import re
import urllib.request
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124 Safari/537.36", "Accept-Language": "en-US,en;q=0.9"}
ET, WIB = ZoneInfo("America/New_York"), ZoneInfo("Asia/Jakarta")
BULAN_EN = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                         "september", "october", "november", "december"], 1)}
BULAN_ID = {m: i for i, m in enumerate(["januari", "februari", "maret", "april", "mei", "juni", "juli", "agustus",
                                         "september", "oktober", "november", "desember"], 1)}
NAMA_BULAN = ["", "Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober",
              "November", "Desember"]


def unduh(url, timeout=30):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        print(f"  gagal unduh {url}: {e}")
        return None


def angka(s):
    return float(s.replace(",", ""))


# ---------------------------------------------------------------- indikator
def te_meta(jalur):
    """Kalimat ringkasan di halaman tradingeconomics.com/<jalur>."""
    b = unduh(f"https://tradingeconomics.com/{jalur}")
    m = re.search(r'id="metaDesc" name="description" content="([^"]+)"', b or "")
    return html.unescape(m.group(1)) if m else None


def te_komoditas(jalur):
    """Contoh kalimat: 'Coal fell to 144.70 USD/T on September 23, 2026, down 0.48% ...'"""
    teks = te_meta(f"commodity/{jalur}")
    m = re.search(r"(?:rose|fell|increased|decreased|was|traded|remained)[^0-9]*?([\d,]+\.?\d*)\s*[A-Z]{3}/\w+ on (\w+ \d{1,2}, \d{4})", teks or "")
    if not m:
        return None
    tgl = datetime.strptime(m.group(2), "%B %d, %Y").date()
    return {"v": angka(m.group(1)), "tanggal": tgl.isoformat(), "sumber": "tradingeconomics"}


def timah_westmetall():
    b = unduh("https://www.westmetall.com/en/markdaten.php?action=table&field=LME_Sn_cash")
    m = re.search(r"<td[^>]*>(\d{1,2})\. (\w+) (\d{4})</td>\s*<td[^>]*>([\d,]+\.\d+)</td>", b or "")
    if not m:
        return None
    tgl = date(int(m.group(3)), BULAN_EN[m.group(2).lower()], int(m.group(1)))
    return {"v": angka(m.group(4)), "tanggal": tgl.isoformat(), "sumber": "westmetall (LME cash)"}


def bi_rate():
    """Riwayat keputusan BI-Rate dari bi.go.id: [(tanggal, nilai), ...] terbaru dulu."""
    b = unduh("https://www.bi.go.id/id/statistik/indikator/bi-rate.aspx")
    if not b:
        return None
    teks = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", b))
    baris = []
    for d, bln, th, v in re.findall(r"(\d{1,2}) (\w+) (20\d\d)\s+([\d.,]+) ?%", teks):
        if bln.lower() in BULAN_ID:
            baris.append((date(int(th), BULAN_ID[bln.lower()], int(d)).isoformat(), float(v.replace(",", "."))))
    baris = sorted(set(baris), reverse=True)
    if not baris:
        return None
    v, tgl = baris[0][1], baris[0][0]
    sebelumnya = next((x[1] for x in baris[1:]), v)
    arah = "naik" if v > sebelumnya else "turun" if v < sebelumnya else "tahan"
    return {"v": v, "arah": arah, "tanggal": tgl, "sumber": "bi.go.id"}


def fed_funds():
    """Batas atas Fed Funds, contoh: 'The benchmark interest rate ... was last recorded at 4 percent.'"""
    teks = te_meta("united-states/interest-rate")
    m = re.search(r"last recorded at ([\d.]+) percent", teks or "")
    return {"v": float(m.group(1)), "sumber": "tradingeconomics"} if m else None


def inflasi_as():
    """Arah inflasi AS: 'Inflation Rate in the United States remained unchanged at 3.40 percent in August.'"""
    teks = te_meta("united-states/inflation-cpi")
    if not teks:
        return None
    m = re.search(r"(increased|rose|accelerated|decreased|fell|eased|slowed|declined|remained unchanged|was unchanged)"
                  r"[^0-9]*([\d.]+) percent in (\w+)", teks)
    if not m:
        return None
    melambat = m.group(1) in ("decreased", "fell", "eased", "slowed", "declined")
    return {"v": float(m.group(2)), "bulan": m.group(3), "melambat": melambat, "kalimat": teks.split(". This page")[0]}


# ---------------------------------------------------------------- kalender
def ke_wib(tgl, jam, menit, zona=ET):
    return datetime(tgl.year, tgl.month, tgl.day, jam, menit, tzinfo=zona).astimezone(WIB)


def fmt_jam(dt):
    return f"{dt.hour:02d}.{dt.minute:02d} WIB"


def jadwal_fomc():
    """Keputusan FOMC (hari kedua rapat, 14.00 ET) untuk semua tahun di halaman Fed."""
    b = unduh("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm")
    if not b:
        return []
    acara = []
    for th, isi in re.findall(r"(\d{4}) FOMC Meetings(.*?)(?=\d{4} FOMC Meetings|$)", b, re.S):
        bulan = re.findall(r"fomc-meeting__month[^>]*>\s*<strong>([^<]+)</strong>", isi)
        hari = re.findall(r"fomc-meeting__date[^>]*>([^<]+)<", isi)
        for bl, hr in zip(bulan, hari):
            nama_bl = bl.split("/")[-1].strip().lower()
            m = re.findall(r"\d{1,2}", hr)
            if nama_bl[:3] not in [k[:3] for k in BULAN_EN] or not m:
                continue
            bln = next(v for k, v in BULAN_EN.items() if k[:3] == nama_bl[:3])
            tgl = date(int(th), bln, int(m[-1]))
            dt = ke_wib(tgl, 14, 0)
            proyeksi = "*" in hr
            acara.append({"tipe": "fomc", "tanggal": dt.date().isoformat(), "jam": fmt_jam(dt), "wilayah": "global",
                          "dampak": "tinggi",
                          "judul": f"Keputusan suku bunga The Fed (FOMC {NAMA_BULAN[bln]} {th})" + (" + proyeksi dot plot" if proyeksi else ""),
                          "catatan": "Arah bunga AS menentukan dolar, yield, dan aliran dana asing ke Indonesia."})
    return acara


def jadwal_bea():
    """PDB AS dan PCE (Personal Income and Outlays) dari jadwal resmi BEA, 08.30 ET."""
    b = unduh("https://www.bea.gov/news/schedule")
    if not b:
        return []
    teks = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "|", b))
    teks = re.sub(r"(\|\s*)+", "|", teks)
    th = date.today().year
    acara, bulan_lalu = [], 0
    for bl, hr, judul in re.findall(r"\|(January|February|March|April|May|June|July|August|September|October|November|December) "
                                    r"(\d{1,2})\|8:30 AM\|(?:N\|ews\|)?([^|]+)", teks):
        bln = BULAN_EN[bl.lower()]
        if bln < bulan_lalu:  # daftar melewati akhir tahun
            th += 1
        bulan_lalu = bln
        judul = judul.strip()
        dt = ke_wib(date(th, bln, int(hr)), 8, 30)
        if judul.startswith("Personal Income and Outlays"):
            periode = judul.split(",")[-1].strip()
            for en, nomor in BULAN_EN.items():
                periode = re.sub(en, NAMA_BULAN[nomor], periode, flags=re.I)
            acara.append({"tipe": "pce", "tanggal": dt.date().isoformat(), "jam": fmt_jam(dt), "wilayah": "global",
                          "dampak": "tinggi", "judul": f"Inflasi PCE AS ({periode})",
                          "catatan": "PCE adalah acuan inflasi utama The Fed."})
        elif judul.startswith("GDP (Advance") or judul.startswith("GDP (Second") or judul.startswith("GDP (Third"):
            tahap = "awal" if "Advance" in judul else "revisi"
            kw = re.search(r"(\d)(?:st|nd|rd|th) Quarter (\d{4})", judul)
            label = f"kuartal {'I II III IV'.split()[int(kw.group(1)) - 1]} {kw.group(2)}" if kw else ""
            acara.append({"tipe": "pdb-as", "tanggal": dt.date().isoformat(), "jam": fmt_jam(dt), "wilayah": "global",
                          "dampak": "tinggi" if tahap == "awal" else "sedang", "judul": f"PDB AS {label} ({tahap})".replace("  ", " "),
                          "catatan": "Pertumbuhan ekonomi AS memengaruhi yield dan arah bunga The Fed."})
    return acara


TE_PETA = {  # jalur tradingeconomics -> (tipe, wilayah, dampak, judul, catatan)
    "/united-states/non-farm-payrolls": ("nfp", "global", "tinggi", "Data tenaga kerja AS (NFP)",
                                         "Data kuat membuat The Fed tetap ketat: yield dan dolar naik."),
    "/united-states/inflation-cpi": ("cpi", "global", "tinggi", "Inflasi AS (CPI)", "Penentu utama arah bunga The Fed."),
    "/united-states/producer-prices-change": ("ppi", "global", "sedang", "Inflasi produsen AS (PPI)",
                                              "Sinyal awal tekanan harga ke konsumen."),
    "/indonesia/interest-rate": ("rdg", "lokal", "tinggi", "Keputusan BI Rate (RDG)",
                                 "Arah bunga menentukan rupiah, bank, dan JSMR."),
    "/indonesia/inflation-cpi": ("inflasi-id", "lokal", "sedang", "Inflasi Indonesia (BPS)",
                                 "Inflasi rendah memberi ruang BI menurunkan bunga."),
    "/indonesia/balance-of-trade": ("neraca", "lokal", "sedang", "Neraca perdagangan Indonesia (BPS)",
                                    "Surplus besar menopang rupiah."),
    "/indonesia/gdp-growth-annual": ("pdb-id", "lokal", "tinggi", "Pertumbuhan ekonomi Indonesia (BPS)",
                                     "Kalau melambat, tekanan agar BI melonggarkan bunga bertambah."),
}


def jadwal_te():
    """Konfirmasi jadwal dari kalender tradingeconomics (hanya beberapa hari ke depan). Jam di situs = UTC."""
    acara = []
    for negara in ("united-states", "indonesia"):
        b = unduh(f"https://tradingeconomics.com/{negara}/calendar")
        if not b:
            continue
        # tanggal ada di header tabel, baris acara di bawahnya
        for blok in re.split(r"(?=<thead)", b):
            h = re.search(r"<th[^>]*colspan[^>]*>\s*(\w+day \w+ \d{1,2} \d{4})", blok)
            if not h:
                continue
            tgl = datetime.strptime(h.group(1), "%A %B %d %Y").date()
            for url, isi in re.findall(r'<tr[^>]*data-url="([^"]+)"[^>]*>(.*?)</tr>', blok, re.S):
                if url not in TE_PETA:
                    continue
                jam = re.search(r"(\d{1,2}):(\d{2}) (AM|PM)", isi)
                if not jam:
                    continue
                j = int(jam.group(1)) % 12 + (12 if jam.group(3) == "PM" else 0)
                dt = datetime(tgl.year, tgl.month, tgl.day, j, int(jam.group(2)), tzinfo=ZoneInfo("UTC")).astimezone(WIB)
                tipe, wil, dampak, judul, cat = TE_PETA[url]
                acara.append({"tipe": tipe, "tanggal": dt.date().isoformat(), "jam": fmt_jam(dt), "wilayah": wil,
                              "dampak": dampak, "judul": judul, "catatan": cat})
    return acara


def libur(d):
    """Libur tetap yang pasti (tahun baru; hari raya lain berubah tiap tahun, jadi tetap diberi label perkiraan)."""
    return (d.month, d.day) in ((1, 1), (12, 25))


def hari_kerja(d):
    while d.weekday() >= 5 or libur(d):
        d += timedelta(days=1)
    return d


def jumat_pertama(th, bl):
    d = date(th, bl, 1)
    d += timedelta(days=(4 - d.weekday()) % 7)
    return d + timedelta(days=7) if d.day <= 2 and bl in (1, 7) else d  # tahun baru / 4 Juli: BLS mundur sepekan


def rabu_ketiga(th, bl):
    d = date(th, bl, 1)
    return d + timedelta(days=(2 - d.weekday()) % 7 + 14)


def perkiraan_pola(mulai, akhir):
    """Acara berulang yang tanggal pastinya belum terbit: diperkirakan dari pola rilis biasa."""
    acara = []
    d = date(mulai.year, mulai.month, 1)
    while d <= akhir:
        th, bl = d.year, d.month
        bl_lalu = NAMA_BULAN[12 if bl == 1 else bl - 1]
        nfp = ke_wib(jumat_pertama(th, bl), 8, 30)
        acara.append({"tipe": "nfp", "tanggal": nfp.date().isoformat(), "jam": fmt_jam(nfp), "wilayah": "global",
                      "dampak": "tinggi", "judul": f"Data tenaga kerja AS (NFP) {bl_lalu}",
                      "catatan": "Data kuat membuat The Fed tetap ketat: yield dan dolar naik."})
        cpi = ke_wib(hari_kerja(date(th, bl, 12)), 8, 30)
        acara.append({"tipe": "cpi", "tanggal": cpi.date().isoformat(), "jam": fmt_jam(cpi), "wilayah": "global",
                      "dampak": "tinggi", "judul": f"Inflasi AS (CPI) {bl_lalu}", "catatan": "Penentu utama arah bunga The Fed."})
        rdg = rabu_ketiga(th, bl)
        acara.append({"tipe": "rdg", "tanggal": rdg.isoformat(), "jam": "±14.30 WIB", "wilayah": "lokal", "dampak": "tinggi",
                      "judul": "Keputusan BI Rate (RDG)", "catatan": "Arah bunga menentukan rupiah, bank, dan JSMR."})
        acara.append({"tipe": "inflasi-id", "tanggal": hari_kerja(date(th, bl, 1)).isoformat(), "jam": "±11.00 WIB",
                      "wilayah": "lokal", "dampak": "sedang", "judul": f"Inflasi Indonesia {bl_lalu} (BPS)",
                      "catatan": "Inflasi rendah memberi ruang BI menurunkan bunga."})
        acara.append({"tipe": "neraca", "tanggal": hari_kerja(date(th, bl, 15)).isoformat(), "jam": "±11.00 WIB",
                      "wilayah": "lokal", "dampak": "sedang", "judul": f"Neraca perdagangan Indonesia {bl_lalu} (BPS)",
                      "catatan": "Surplus besar menopang rupiah."})
        if bl in (2, 5, 8, 11):
            kw = {2: "IV", 5: "I", 8: "II", 11: "III"}[bl]
            acara.append({"tipe": "pdb-id", "tanggal": hari_kerja(date(th, bl, 5)).isoformat(), "jam": "±11.00 WIB",
                          "wilayah": "lokal", "dampak": "tinggi", "judul": f"Pertumbuhan ekonomi Indonesia kuartal {kw} (BPS)",
                          "catatan": "Kalau melambat, tekanan agar BI melonggarkan bunga bertambah."})
        d = date(th + (bl == 12), bl % 12 + 1, 1)
    for a in acara:
        a["perkiraan"] = True
    return [a for a in acara if mulai <= date.fromisoformat(a["tanggal"]) <= akhir]
