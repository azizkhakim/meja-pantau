"""Ambil harga pasar terbaru, hitung level teknikal saham, simpan ke folder data/.

- data/market.json : indikator otomatis (IHSG, yield AS, DXY, rupiah, emas, Brent)
- data/sinyal.json : level teknikal tiap saham di data/peta.json (entry, cut loss, take profit)

Dijalankan otomatis oleh GitHub Actions (lihat .github/workflows/update-market.yml).
Bisa juga dijalankan manual:  python3 scripts/update_market.py

Hanya memakai pustaka bawaan Python, jadi tidak perlu `pip install`.
Kalau satu simbol gagal diambil, nilai lama tetap dipakai dan ditandai `lama: true`,
sehingga halaman tidak pernah kosong.

Level teknikal dihitung dengan aturan tetap (lihat fungsi `setup_teknikal`).
Ini alat bantu, bukan rekomendasi jual/beli.
"""

import json
import os
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import sumber

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT_MARKET = DATA / "market.json"
OUT_SINYAL = DATA / "sinyal.json"
OUT_JURNAL = DATA / "jurnal.json"
OUT_NOTIF = DATA / "notif.json"
WIB = timezone(timedelta(hours=7))

# kunci indikator di halaman -> simbol Yahoo Finance
INDIKATOR = {
    "ihsg": "^JKSE",
    "us10y": "^TNX",
    "dxy": "DX-Y.NYB",
    "usdidr": "IDR=X",
    "emas": "GC=F",
    "brent": "BZ=F",
}

URL = "https://query1.finance.yahoo.com/v8/finance/chart/{}?range={}&interval=1d"
HEADERS = {"User-Agent": "Mozilla/5.0 (IHSG Makro Monitor; pemakaian pribadi)"}

# ---- aturan teknikal (ubah di sini kalau mau lebih longgar/ketat) ----
# Aturan ini lolos backtest 2 tahun (lihat scripts/backtest.py); versi tanpa filter pasar & kekuatan relatif rugi.
RSI_JENUH_BELI = 75      # di atas ini: tunggu koreksi
MA50_NAIK_HARI = 10      # MA50 hari ini harus di atas MA50 10 hari lalu
KUAT_HARI = 60           # saham harus naik lebih banyak dari IHSG dalam 60 hari terakhir
RISIKO_MAKS = 0.09       # jarak cut loss maksimal 9% dari entry
RR_TP1 = 1.5             # take profit 1 = 1,5x risiko
RR_TP2 = 2.5             # take profit 2 = 2,5x risiko (atau harga tertinggi 60 hari kalau lebih tinggi)
LIKUID_MIN = 5e9         # nilai transaksi rata-rata 20 hari minimal Rp5 miliar/hari

# ---- aturan eksekusi (dipakai jurnal dan backtest) ----
BERLAKU_ORDER = 5        # order beli berlaku 5 hari bursa setelah sinyal
MAKS_TAHAN = 20          # posisi ditutup setelah 20 hari bursa
# Jual separuh di TP1 lalu cut loss dipindah ke harga beli; sisanya di TP2.


def ambil(simbol, rentang="5d"):
    """Kembalikan data harian satu simbol, atau None kalau gagal."""
    url = URL.format(urllib.parse.quote(simbol), rentang)
    for percobaan in range(3):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.load(resp)
            res = data["chart"]["result"][0]
            meta = res["meta"]
            if meta.get("regularMarketPrice") is None:
                return None
            q = res["indicators"]["quote"][0]
            baris = [
                {"t": w, "o": o, "h": h, "l": l, "c": c, "vol": vol or 0}
                for w, o, h, l, c, vol in zip(res.get("timestamp") or [], q["open"], q["high"], q["low"], q["close"], q["volume"])
                if None not in (o, h, l, c)
            ]
            return {"meta": meta, "baris": baris}
        except Exception as e:  # jaringan putus, format berubah, dsb.
            print(f"  gagal {simbol} (percobaan {percobaan + 1}): {e}")
            time.sleep(2 * (percobaan + 1))
    return None


def ringkas(data):
    """{v, prev, t}: harga terakhir, penutupan hari sebelumnya, waktu harga."""
    meta, baris = data["meta"], data["baris"]
    t = meta.get("regularMarketTime")
    hari_ini = datetime.fromtimestamp(t, timezone.utc).date() if t else None
    sebelum = [b["c"] for b in baris if hari_ini is None or datetime.fromtimestamp(b["t"], timezone.utc).date() < hari_ini]
    return {
        "v": round(float(meta["regularMarketPrice"]), 4),
        "prev": round(float(sebelum[-1]), 4) if sebelum else None,
        "t": datetime.fromtimestamp(t, timezone.utc).isoformat() if t else None,
    }


def fraksi(harga):
    """Fraksi harga (tick size) BEI."""
    if harga < 200:
        return 1
    if harga < 500:
        return 2
    if harga < 2000:
        return 5
    if harga < 5000:
        return 10
    return 25


def bulat(harga):
    """Bulatkan ke bawah sesuai fraksi harga BEI."""
    f = fraksi(harga)
    return int(harga // f * f)


def rata(xs):
    return sum(xs) / len(xs) if xs else None


def konteks_pasar(baris_ihsg):
    """Kondisi IHSG: di atas MA50 atau tidak, dan kenaikan 60 hari (dipakai filter)."""
    c = [b["c"] for b in baris_ihsg]
    if len(c) < max(50, KUAT_HARI + 1):
        return None
    ma50 = rata(c[-50:])
    return {"ihsg": round(c[-1], 1), "ihsg_ma50": round(ma50, 1), "ihsg_kuat": c[-1] > ma50,
            "ihsg_ret60": round(c[-1] / c[-1 - KUAT_HARI] - 1, 4)}


def setup_teknikal(baris, harga, pasar=None):
    """Hitung tren dan level entry / cut loss / take profit dengan aturan tetap.

    pasar: hasil konteks_pasar(); kalau None, filter pasar dan kekuatan relatif dilewati.
    """
    if len(baris) < max(60, MA50_NAIK_HARI + 50, KUAT_HARI + 1):
        return {"setup": "tunggu", "alasan": "Data harga kurang dari 60 hari."}

    c = [b["c"] for b in baris]
    h = [b["h"] for b in baris]
    l = [b["l"] for b in baris]
    c[-1] = harga  # pakai harga terakhir (bisa di tengah sesi)

    ma20, ma50 = rata(c[-20:]), rata(c[-50:])
    tr = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
    atr = rata(tr[-14:])
    naik = [max(c[i] - c[i - 1], 0) for i in range(len(c) - 14, len(c))]
    turun = [max(c[i - 1] - c[i], 0) for i in range(len(c) - 14, len(c))]
    rsi = 100.0 if rata(turun) == 0 else 100 - 100 / (1 + rata(naik) / rata(turun))
    tinggi60 = max(h[-60:])
    ma50_lalu = rata(c[-50 - MA50_NAIK_HARI:-MA50_NAIK_HARI])
    ret60 = c[-1] / c[-1 - KUAT_HARI] - 1

    if harga > ma50 and ma20 > ma50:
        tren = "naik"
    elif harga < ma50 and ma20 < ma50:
        tren = "turun"
    else:
        tren = "datar"

    nilai_tx = rata([b["c"] * b["vol"] for b in baris[-20:]]) or 0
    info = {"tren": tren, "ma20": bulat(ma20), "ma50": bulat(ma50), "atr": round(atr, 1), "rsi": round(rsi, 1),
            "nilai_tx_mlr": round(nilai_tx / 1e9, 1)}

    if nilai_tx < LIKUID_MIN:
        return {**info, "setup": "tunggu",
                "alasan": f"Kurang likuid (rata-rata Rp{nilai_tx / 1e9:.1f} miliar/hari). Cut loss bisa sulit dieksekusi."}

    def level(e_bawah, e_atas, cl, jenis, alasan):
        e_bawah, e_atas = bulat(e_bawah), bulat(e_atas)
        if e_atas < e_bawah:
            e_bawah, e_atas = e_atas, e_bawah
        tengah = (e_bawah + e_atas) / 2
        cl = bulat(cl)
        risiko = tengah - cl
        if risiko <= 0 or risiko / tengah > RISIKO_MAKS:
            return {**info, "setup": "tunggu",
                    "alasan": f"Jarak cut loss terlalu lebar (>{int(RISIKO_MAKS * 100)}%). Tunggu harga lebih tenang."}
        tp1 = bulat(tengah + RR_TP1 * risiko)
        tp2_rr = tengah + RR_TP2 * risiko
        tp2 = bulat(max(tp2_rr, tinggi60) if tinggi60 > tp1 else tp2_rr)
        return {**info, "setup": jenis, "entry": [e_bawah, e_atas], "cl": cl, "tp1": tp1, "tp2": tp2,
                "rr2": round((tp2 - tengah) / risiko, 1), "risiko_pct": round(risiko / tengah * 100, 1), "alasan": alasan}

    if rsi > RSI_JENUH_BELI:
        return {**info, "setup": "tunggu", "alasan": f"RSI {rsi:.0f}, jenuh beli. Tunggu koreksi."}
    if tren == "turun":
        return {**info, "setup": "tunggu", "alasan": "Tren turun (harga dan MA20 di bawah MA50)."}
    if tren == "naik" and ma20 - 0.5 * atr <= harga <= ma20 + 1.0 * atr:
        if ma50 <= ma50_lalu:
            return {**info, "setup": "tunggu", "alasan": "Dekat MA20, tapi MA50 belum menanjak. Tren belum cukup kuat."}
        if pasar and ret60 <= pasar["ihsg_ret60"]:
            return {**info, "setup": "tunggu",
                    "alasan": f"Dekat MA20, tapi kalah kuat dari IHSG dalam {KUAT_HARI} hari ({ret60 * 100:+.1f}% vs {pasar['ihsg_ret60'] * 100:+.1f}%)."}
        e_bawah = ma20 - 0.5 * atr
        s = level(e_bawah, min(harga, ma20 + 0.5 * atr), e_bawah - 1.2 * atr, "pullback",
                  "Tren naik, MA50 menanjak, lebih kuat dari IHSG, dan harga kembali dekat MA20.")
        if s["setup"] == "pullback" and pasar and not pasar["ihsg_kuat"]:
            return {**s, "setup": "tunggu", "siap_jika_pasar_pulih": True,
                    "alasan": "Pola sudah siap, tapi IHSG di bawah MA50. Secara historis sinyal beli saat pasar lemah lebih sering gagal. Tunggu IHSG kembali ke atas MA50."}
        return s
    if tren == "naik" and harga > ma20:
        return {**info, "setup": "tunggu", "area_tunggu": [bulat(ma20 - 0.5 * atr), bulat(ma20 + 0.5 * atr)],
                "alasan": f"Sudah naik jauh dari MA20. Tunggu koreksi ke sekitar {bulat(ma20)}."}
    if tren == "naik":
        return {**info, "setup": "tunggu",
                "alasan": f"Terkoreksi ke bawah MA20 ({bulat(ma20)}). Tunggu harga kembali ke atas {bulat(ma20 - 0.5 * atr)} sebelum masuk."}
    return {**info, "setup": "tunggu", "alasan": "Belum ada tren yang jelas."}


def jalankan_posisi(baris, mulai, atas, cl, tp1, tp2, bagi_dua=True):
    """Simulasikan order beli & pengelolaan posisi mulai dari indeks `mulai` (hari setelah sinyal).

    Kembalikan dict status: menunggu | batal | terbuka | tp2 | tp1+impas | tp1 | cut loss |
    habis waktu | tp1+habis waktu, plus harga beli/jual dan indeks hari.
    bagi_dua=False: jual semua di TP1.
    """
    o = [b["o"] for b in baris]
    h = [b["h"] for b in baris]
    l = [b["l"] for b in baris]
    c = [b["c"] for b in baris]
    n = len(baris)

    isi, beli = None, None
    for d in range(mulai, min(mulai + BERLAKU_ORDER, n)):
        if o[d] <= cl:
            return {"status": "batal", "alasan": "dibuka di bawah cut loss"}
        if o[d] <= atas:
            isi, beli = d, o[d]
            break
        if l[d] <= atas:
            isi, beli = d, atas
            break
    if isi is None:
        return {"status": "batal", "alasan": "harga tidak turun ke area entry"} if mulai + BERLAKU_ORDER <= n else {"status": "menunggu"}

    sl, sisa, uang, tp1_kena = cl, 1.0, 0.0, False
    for d in range(isi, min(isi + MAKS_TAHAN, n)):
        buka = o[d] if d > isi else beli
        if l[d] <= sl:
            jual = uang + sisa * min(buka, sl)
            return {"status": "tp1+impas" if tp1_kena else "cut loss", "isi": isi, "beli": beli, "keluar": d, "jual": jual}
        if not tp1_kena and h[d] >= tp1:
            if not bagi_dua:
                return {"status": "tp1", "isi": isi, "beli": beli, "keluar": d, "jual": tp1}
            uang, sisa, tp1_kena, sl = 0.5 * tp1, 0.5, True, beli
        if tp1_kena and h[d] >= tp2:
            return {"status": "tp2", "isi": isi, "beli": beli, "keluar": d, "jual": uang + sisa * tp2}
    if isi + MAKS_TAHAN <= n:
        d = isi + MAKS_TAHAN - 1
        return {"status": "tp1+habis waktu" if tp1_kena else "habis waktu", "isi": isi, "beli": beli, "keluar": d,
                "jual": uang + sisa * c[d]}
    return {"status": "terbuka", "isi": isi, "beli": beli, "tp1_kena": tp1_kena, "sl": sl}


BIAYA_BELI, BIAYA_JUAL = 0.0015, 0.0025


def hasil_bersih(beli, jual):
    return jual * (1 - BIAYA_JUAL) / (beli * (1 + BIAYA_BELI)) - 1


# ---------------- jurnal & notifikasi ----------------
def tgl_wib(ts):
    return datetime.fromtimestamp(ts, WIB).date().isoformat()


def perbarui_jurnal(jurnal, sinyal, data_saham, tema_saham):
    """Catat sinyal baru dan perbarui status catatan lama. Kembalikan daftar pesan notifikasi."""
    pesan = []
    catatan = jurnal.setdefault("catatan", [])
    hari_ini = datetime.now(WIB).date().isoformat()

    # perbarui catatan yang belum selesai
    for cat in catatan:
        if cat["status"] not in ("menunggu", "terbuka"):
            continue
        baris = data_saham.get(cat["saham"])
        if not baris:
            continue
        idx = [i for i, b in enumerate(baris) if tgl_wib(b["t"]) <= cat["tanggal"]]
        if not idx:
            continue
        r = jalankan_posisi(baris, idx[-1] + 1, cat["entry"][1], cat["cl"], cat["tp1"], cat["tp2"])
        lama, baru = cat["status"], r["status"]
        tp1_lama = cat.get("tp1_kena", False)
        cat["status"] = baru
        cat["diperbarui"] = hari_ini
        if "beli" in r:
            cat["beli"] = round(r["beli"], 1)
            cat["tgl_beli"] = tgl_wib(baris[r["isi"]]["t"])
        if "jual" in r:
            cat["hasil_pct"] = round(hasil_bersih(r["beli"], r["jual"]) * 100, 2)
            cat["tgl_keluar"] = tgl_wib(baris[r["keluar"]]["t"])
        if baru == "batal":
            cat["alasan_batal"] = r.get("alasan")
        cat["tp1_kena"] = r.get("tp1_kena", baru in ("tp2", "tp1+impas", "tp1+habis waktu"))

        tk = cat["saham"]
        if lama == "menunggu" and baru != "menunggu":
            if baru == "batal":
                pesan.append(f"⚪ {tk}: sinyal batal ({r.get('alasan')}).")
            else:
                pesan.append(f"🔵 {tk}: order terisi di {fmt(cat['beli'])}. Cut loss {fmt(cat['cl'])}, TP1 {fmt(cat['tp1'])}, TP2 {fmt(cat['tp2'])}.")
        if cat["tp1_kena"] and not tp1_lama:
            pesan.append(f"✅ {tk}: TP1 {fmt(cat['tp1'])} tercapai. Jual separuh, pindahkan cut loss ke harga beli {fmt(cat.get('beli'))}.")
        if baru in ("tp2", "tp1+impas", "cut loss", "habis waktu", "tp1+habis waktu") and lama != baru:
            ikon = "🏁" if baru == "tp2" else "🔴" if baru == "cut loss" else "⏱️"
            pesan.append(f"{ikon} {tk}: posisi selesai ({baru}), hasil bersih {cat['hasil_pct']:+.2f}%.")

    # catat sinyal baru
    aktif = {c["saham"] for c in catatan if c["status"] in ("menunggu", "terbuka")}
    for tk, s in sinyal["saham"].items():
        if s.get("setup") != "pullback" or tk in aktif or s.get("lama"):
            continue
        tema = [v["label"] for v in tema_saham.values() if tk in v["saham"]]
        catatan.append({"id": f"{tk}-{hari_ini}", "saham": tk, "tanggal": hari_ini, "entry": s["entry"], "cl": s["cl"],
                        "tp1": s["tp1"], "tp2": s["tp2"], "harga_sinyal": s["v"], "tema": tema, "status": "menunggu",
                        "diperbarui": hari_ini})
        pesan.append(f"🟢 Kandidat baru: {tk} ({', '.join(tema)})\nEntry {fmt(s['entry'][0])}–{fmt(s['entry'][1])} · Cut loss {fmt(s['cl'])} · TP1 {fmt(s['tp1'])} · TP2 {fmt(s['tp2'])}\nHarga sekarang {fmt(s['v'])}. Order berlaku 5 hari bursa.")

    selesai = [c for c in catatan if "hasil_pct" in c and c["status"] not in ("terbuka",)]
    if selesai:
        hs = [c["hasil_pct"] for c in selesai]
        jurnal["rapor"] = {"selesai": len(hs), "menang": sum(1 for x in hs if x > 0),
                           "rata_pct": round(sum(hs) / len(hs), 2), "total_pct": round(sum(hs), 2)}
    jurnal["diperbarui"] = datetime.now(timezone.utc).isoformat()
    return pesan


def fmt(x):
    return "-" if x is None else f"{x:,.0f}".replace(",", ".")


def pesan_agenda(notif):
    """Pengingat acara berdampak tinggi untuk hari ini dan besok (sekali per acara per hari)."""
    agenda_file = DATA / "agenda.json"
    if not agenda_file.exists():
        return []
    sekarang = datetime.now(WIB)
    if sekarang.hour >= 10:  # hanya di pembaruan pagi
        return []
    hari_ini = sekarang.date()
    pesan = []
    for e in json.loads(agenda_file.read_text(encoding="utf-8")):
        if e.get("dampak") != "tinggi":
            continue
        selisih = (datetime.fromisoformat(e["tanggal"]).date() - hari_ini).days
        if selisih not in (0, 1):
            continue
        kunci = f"agenda:{e['id']}:{selisih}"
        if kunci in notif["terkirim"]:
            continue
        notif["terkirim"].append(kunci)
        pesan.append(f"📅 {'Hari ini' if selisih == 0 else 'Besok'} {e.get('jam', '')}: {e['judul']}\n{e.get('catatan', '')}")
    return pesan


def kirim_telegram(pesan):
    """Kirim pesan; kembalikan True kalau semua terkirim."""
    token, chat = os.environ.get("TELEGRAM_TOKEN", "").strip(), os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not pesan:
        return True
    if not token or not chat:
        print("Telegram belum diatur; pesan tidak dikirim:\n  " + "\n  ".join(p.replace("\n", " | ") for p in pesan))
        return False
    teks = "IHSG & Makro Monitor\n\n" + "\n\n".join(pesan)
    ok = True
    for bagian in [teks[i:i + 3900] for i in range(0, len(teks), 3900)]:
        data = urllib.parse.urlencode({"chat_id": chat, "text": bagian, "disable_web_page_preview": "true"}).encode()
        try:
            urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=20).read()
        except Exception as e:
            ok = False
            print(f"  gagal kirim Telegram: {e} (cek TELEGRAM_TOKEN dan TELEGRAM_CHAT_ID, dan pastikan sudah mengirim pesan ke bot)")
    return ok


TIPE_OTOMATIS = {"fomc", "pce", "pdb-as", "nfp", "cpi", "ppi", "rdg", "inflasi-id", "neraca", "pdb-id"}
TIPE_DARI_ID = {"fomc": "fomc", "gdp": "pdb-as", "pce": "pce", "nfp": "nfp", "cpi": "cpi", "ppi": "ppi", "rdg": "rdg",
                "inflasi": "inflasi-id", "neraca": "neraca", "pdb": "pdb-id"}


def perbarui_agenda(fomc):
    """Susun ulang acara berulang: jadwal resmi (Fed, BEA, tradingeconomics) diutamakan, sisanya perkiraan pola.

    Acara yang kamu tambahkan sendiri (tipe lain) tidak disentuh.
    """
    f = DATA / "agenda.json"
    lama = json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
    hari_ini = datetime.now(WIB).date()
    awal, akhir = hari_ini - timedelta(days=30), hari_ini + timedelta(days=120)

    resmi = fomc + sumber.jadwal_bea() + sumber.jadwal_te()
    pola = sumber.perkiraan_pola(hari_ini, akhir)

    def tipe_dari(e):
        return e.get("tipe") or TIPE_DARI_ID.get(e["id"].split("-")[-1])

    # acara lama yang sudah lewat atau sudah pasti (bukan perkiraan) tetap disimpan
    dipakai = {}
    for e in lama:
        t = tipe_dari(e)
        if t in TIPE_OTOMATIS and (date.fromisoformat(e["tanggal"]) < hari_ini or not e.get("perkiraan")):
            dipakai[(t, e["tanggal"][:7])] = {**e, "tipe": t}
    for e in pola:
        kunci = (e["tipe"], e["tanggal"][:7])
        if kunci not in dipakai or dipakai[kunci].get("perkiraan"):
            dipakai[kunci] = e
    for e in resmi:
        kunci = (e["tipe"], e["tanggal"][:7])
        sekarang_ada = dipakai.get(kunci)
        if sekarang_ada and not sekarang_ada.get("perkiraan") and sekarang_ada["tanggal"] != e["tanggal"] and e["tipe"] in ("pdb-as", "pce"):
            kunci = (e["tipe"], e["tanggal"])  # BEA bisa merilis dua kali sebulan
        e = {**e}
        e.pop("perkiraan", None)
        if sekarang_ada and len(sekarang_ada.get("judul", "")) > len(e["judul"]) and "+" not in sekarang_ada["judul"]:
            e["judul"] = sekarang_ada["judul"]  # pertahankan judul yang lebih lengkap (mis. ada nama bulannya)
        dipakai[kunci] = e

    otomatis = []
    for e in dipakai.values():
        if not (awal <= date.fromisoformat(e["tanggal"]) <= akhir):
            continue
        e = {k: v for k, v in e.items() if k != "id"}
        e["id"] = f"{e['tanggal']}-{e['tipe']}"
        e["otomatis"] = True
        otomatis.append(e)
    sendiri = [e for e in lama if tipe_dari(e) not in TIPE_OTOMATIS and date.fromisoformat(e["tanggal"]) >= awal]
    baru = sorted(otomatis + sendiri, key=lambda e: (e["tanggal"], e.get("jam", "")))
    urutan = ["id", "tanggal", "jam", "wilayah", "dampak", "judul", "catatan", "perkiraan", "tipe", "otomatis"]
    teks = "[\n" + ",\n".join("  " + json.dumps({k: e[k] for k in urutan if k in e} | {k: v for k, v in e.items() if k not in urutan},
                                                ensure_ascii=False) for e in baru) + "\n]\n"
    f.write_text(teks, encoding="utf-8")
    print(f"Kalender: {len(otomatis)} otomatis ({sum(1 for e in otomatis if e.get('perkiraan'))} perkiraan), {len(sendiri)} buatan sendiri")


def daftar_saham():
    kode = set()
    peta = DATA / "peta.json"
    if peta.exists():
        for tema in json.loads(peta.read_text(encoding="utf-8")).get("tema", {}).values():
            kode.update(k.upper() for k in tema.get("saham", []))
    file_saham = DATA / "saham.json"  # opsional, dari versi lama
    if file_saham.exists():
        kode.update(s["ticker"].upper() for s in json.loads(file_saham.read_text(encoding="utf-8")))
    return sorted(kode)


def baca(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def main():
    sekarang = datetime.now(timezone.utc).isoformat()
    lama_market, lama_sinyal = baca(OUT_MARKET), baca(OUT_SINYAL)
    gagal = []

    # 1) indikator
    market = {"diperbarui": sekarang, "indikator": {}}
    for kunci, simbol in INDIKATOR.items():
        data = ambil(simbol)
        if data:
            q = ringkas(data)
            if kunci == "us10y" and q["v"] > 20:  # jaga-jaga kalau yield dikutip x10
                q = {**q, "v": round(q["v"] / 10, 3), "prev": round(q["prev"] / 10, 3) if q["prev"] else None}
            market["indikator"][kunci] = q
        else:
            gagal.append(simbol)
            if kunci in lama_market.get("indikator", {}):
                market["indikator"][kunci] = {**lama_market["indikator"][kunci], "lama": True}
    # 1b) indikator dari situs publik (komoditas, suku bunga, inflasi AS) + proksi asing
    diambil = sekarang
    lama_ind = lama_market.get("indikator", {})
    manual = baca(DATA / "manual.json").get("indikator", {})

    def simpan(kunci, nilai, nama):
        if nilai:
            market["indikator"][kunci] = {**nilai, "diambil": diambil}
        else:
            gagal.append(nama)
            if kunci in lama_ind:
                market["indikator"][kunci] = {**lama_ind[kunci], "lama": True}

    simpan("batubara", sumber.te_komoditas("coal"), "batu bara")
    simpan("cpo", sumber.te_komoditas("palm-oil"), "CPO")
    simpan("timah", sumber.te_komoditas("tin") or sumber.timah_westmetall(), "timah")
    simpan("birate", sumber.bi_rate(), "BI Rate")

    fomc = sumber.jadwal_fomc()
    fed = sumber.fed_funds()
    if fed:
        sebelumnya = lama_ind.get("fedfunds") or {**manual.get("fedfunds", {}), "sejak": "2026-09-17"}
        hari_ini = datetime.now(WIB).date().isoformat()
        if sebelumnya.get("v") is not None and fed["v"] != sebelumnya["v"]:
            fed.update(arah="naik" if fed["v"] > sebelumnya["v"] else "turun", sejak=hari_ini)
        else:
            rapat = [a["tanggal"] for a in fomc if a["tanggal"] <= hari_ini]
            terakhir = max(rapat) if rapat else None
            if terakhir and terakhir > sebelumnya.get("sejak", ""):
                fed.update(arah="tahan", sejak=terakhir)
            else:
                fed.update(arah=sebelumnya.get("arah", "tahan"), sejak=sebelumnya.get("sejak", hari_ini))
        fed["tanggal"] = fed["sejak"]
    simpan("fedfunds", fed, "Fed Funds")

    eido = ambil("EIDO", "3mo")
    if eido and len(eido["baris"]) > 21:
        c = [b["c"] for b in eido["baris"]]
        simpan("eido", {"v": round((c[-1] / c[-21] - 1) * 100, 2), "harga": round(c[-1], 2),
                        "tanggal": tgl_wib(eido["baris"][-1]["t"]), "sumber": "Yahoo Finance (EIDO)"}, "EIDO")
    else:
        simpan("eido", None, "EIDO")

    infl = sumber.inflasi_as()
    bi = market["indikator"].get("birate", {})
    market["ceklis"] = {"cpi": infl["melambat"] if infl else lama_market.get("ceklis", {}).get("cpi"),
                        "bi": bi.get("arah") == "turun" if bi else None,
                        "cpi_kalimat": infl["kalimat"] if infl else lama_market.get("ceklis", {}).get("cpi_kalimat")}
    market["gagal"] = list(gagal)

    # 1c) kalender otomatis
    perbarui_agenda(fomc)

    # 2) kondisi pasar (filter) + saham + level teknikal
    ihsg6 = ambil("^JKSE", "6mo")
    pasar = konteks_pasar(ihsg6["baris"]) if ihsg6 else lama_sinyal.get("pasar")
    sinyal = {"diperbarui": sekarang, "pasar": pasar, "saham": {}}
    data_saham = {}
    for tk in daftar_saham():
        data = ambil(f"{tk}.JK", "6mo")
        time.sleep(0.3)  # jeda kecil supaya tidak dibatasi Yahoo
        if data:
            data_saham[tk] = data["baris"]
            q = ringkas(data)
            nama = (data["meta"].get("longName") or data["meta"].get("shortName") or tk).replace("PT ", "").replace(" Tbk", "").strip()
            sinyal["saham"][tk] = {"nama": nama, **q, **setup_teknikal(data["baris"], q["v"], pasar)}
        else:
            gagal.append(f"{tk}.JK")
            if tk in lama_sinyal.get("saham", {}):
                sinyal["saham"][tk] = {**lama_sinyal["saham"][tk], "lama": True}
    sinyal["gagal"] = [g for g in gagal if g.endswith(".JK")]

    # 3) jurnal sinyal + notifikasi
    peta = baca(DATA / "peta.json")
    jurnal = baca(OUT_JURNAL) or {"catatan": []}
    notif = baca(OUT_NOTIF) or {"terkirim": []}
    pesan = perbarui_jurnal(jurnal, sinyal, data_saham, peta.get("tema", {}))
    if pasar and notif.get("ihsg_kuat") is not None and notif["ihsg_kuat"] != pasar["ihsg_kuat"]:
        tahan = [k for k, v in sinyal["saham"].items() if v.get("setup") == "pullback"]
        pesan.insert(0, ("🟢 IHSG kembali di atas MA50" if pasar["ihsg_kuat"] else "🟠 IHSG turun ke bawah MA50") +
                     f" ({fmt(pasar['ihsg'])} vs MA50 {fmt(pasar['ihsg_ma50'])})." +
                     (f" Kandidat aktif: {', '.join(tahan)}." if pasar["ihsg_kuat"] and tahan else
                      "" if pasar["ihsg_kuat"] else " Kandidat baru ditahan sampai pasar pulih."))
    if pasar:
        notif["ihsg_kuat"] = pasar["ihsg_kuat"]
    pesan += pesan_agenda(notif)
    if os.environ.get("TELEGRAM_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID") and not notif.get("telegram_ok"):
        pesan.insert(0, "✅ Telegram terhubung. Mulai sekarang kamu akan menerima: kandidat baru, order terisi, TP/cut loss, "
                        "perubahan IHSG terhadap MA50, dan pengingat pagi sebelum acara berdampak tinggi.")
    notif["terkirim"] = notif["terkirim"][-300:]

    OUT_MARKET.write_text(json.dumps(market, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_SINYAL.write_text(json.dumps(sinyal, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    OUT_JURNAL.write_text(json.dumps(jurnal, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if kirim_telegram(pesan) and os.environ.get("TELEGRAM_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"):
        notif["telegram_ok"] = True
    OUT_NOTIF.write_text(json.dumps(notif, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    siap = [k for k, v in sinyal["saham"].items() if v.get("setup") == "pullback"]
    tahan = [k for k, v in sinyal["saham"].items() if v.get("siap_jika_pasar_pulih")]
    print(f"Pasar: {pasar} · Tertahan filter IHSG: {tahan}")
    print(f"Indikator: {len(market['indikator'])}/{len(INDIKATOR)} · Saham: {len(sinyal['saham'])} · Siap entry: {siap} · Gagal: {gagal or '-'}")


if __name__ == "__main__":
    main()
