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
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT_MARKET = DATA / "market.json"
OUT_SINYAL = DATA / "sinyal.json"

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
HEADERS = {"User-Agent": "Mozilla/5.0 (Meja Pantau; pemakaian pribadi)"}

# ---- aturan teknikal (ubah di sini kalau mau lebih longgar/ketat) ----
RSI_JENUH_BELI = 75      # di atas ini: tunggu koreksi
VOL_BREAKOUT = 1.5       # volume hari ini minimal 1,5x rata-rata 20 hari
RISIKO_MAKS = 0.09       # jarak cut loss maksimal 9% dari entry
RR_TP1 = 1.5             # take profit 1 = 1,5x risiko
RR_TP2 = 2.5             # take profit 2 = 2,5x risiko (atau harga tertinggi 60 hari kalau lebih tinggi)
LIKUID_MIN = 5e9         # nilai transaksi rata-rata 20 hari minimal Rp5 miliar/hari


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


def setup_teknikal(baris, harga):
    """Hitung tren dan level entry / cut loss / take profit dengan aturan tetap."""
    if len(baris) < 60:
        return {"setup": "tunggu", "alasan": "Data harga kurang dari 60 hari."}

    c = [b["c"] for b in baris]
    h = [b["h"] for b in baris]
    l = [b["l"] for b in baris]
    vol = [b["vol"] for b in baris]
    c[-1] = harga  # pakai harga terakhir (bisa di tengah sesi)

    ma20, ma50 = rata(c[-20:]), rata(c[-50:])
    tr = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
    atr = rata(tr[-14:])
    naik = [max(c[i] - c[i - 1], 0) for i in range(len(c) - 14, len(c))]
    turun = [max(c[i - 1] - c[i], 0) for i in range(len(c) - 14, len(c))]
    rsi = 100.0 if rata(turun) == 0 else 100 - 100 / (1 + rata(naik) / rata(turun))
    tinggi20_sebelum = max(h[-21:-1])
    tinggi60 = max(h[-60:])
    vol_rasio = vol[-1] / rata(vol[-21:-1]) if rata(vol[-21:-1]) else 0

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
    if harga >= tinggi20_sebelum and vol_rasio >= VOL_BREAKOUT:
        return level(tinggi20_sebelum, tinggi20_sebelum + 0.5 * atr, tinggi20_sebelum - 1.2 * atr, "breakout",
                     f"Menembus harga tertinggi 20 hari ({bulat(tinggi20_sebelum)}) dengan volume {vol_rasio:.1f}x rata-rata.")
    if tren == "naik" and ma20 - 0.5 * atr <= harga <= ma20 + 1.0 * atr:
        e_bawah = ma20 - 0.5 * atr
        return level(e_bawah, min(harga, ma20 + 0.5 * atr), e_bawah - 1.2 * atr, "pullback",
                     "Tren naik dan harga kembali dekat MA20: area beli saat koreksi.")
    if tren == "naik" and harga > ma20:
        return {**info, "setup": "tunggu", "area_tunggu": [bulat(ma20 - 0.5 * atr), bulat(ma20 + 0.5 * atr)],
                "alasan": f"Sudah naik jauh dari MA20. Tunggu koreksi ke sekitar {bulat(ma20)}."}
    if tren == "naik":
        return {**info, "setup": "tunggu",
                "alasan": f"Terkoreksi ke bawah MA20 ({bulat(ma20)}). Tunggu harga kembali ke atas {bulat(ma20 - 0.5 * atr)} sebelum masuk."}
    return {**info, "setup": "tunggu", "alasan": "Belum ada tren yang jelas."}


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
    market["gagal"] = list(gagal)

    # 2) saham + level teknikal
    sinyal = {"diperbarui": sekarang, "saham": {}}
    for tk in daftar_saham():
        data = ambil(f"{tk}.JK", "6mo")
        if data:
            q = ringkas(data)
            nama = (data["meta"].get("longName") or data["meta"].get("shortName") or tk).replace("PT ", "").replace(" Tbk", "").strip()
            sinyal["saham"][tk] = {"nama": nama, **q, **setup_teknikal(data["baris"], q["v"])}
        else:
            gagal.append(f"{tk}.JK")
            if tk in lama_sinyal.get("saham", {}):
                sinyal["saham"][tk] = {**lama_sinyal["saham"][tk], "lama": True}
    sinyal["gagal"] = [g for g in gagal if g.endswith(".JK")]

    OUT_MARKET.write_text(json.dumps(market, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_SINYAL.write_text(json.dumps(sinyal, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    siap = [k for k, v in sinyal["saham"].items() if v.get("setup") in ("pullback", "breakout")]
    print(f"Indikator: {len(market['indikator'])}/{len(INDIKATOR)} · Saham: {len(sinyal['saham'])} · Siap entry: {siap} · Gagal: {gagal or '-'}")


if __name__ == "__main__":
    main()
