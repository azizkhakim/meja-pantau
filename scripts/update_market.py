"""Ambil harga pasar terbaru dan simpan ke data/market.json.

Dijalankan otomatis oleh GitHub Actions (lihat .github/workflows/update-market.yml).
Bisa juga dijalankan manual:  python3 scripts/update_market.py

Hanya memakai pustaka bawaan Python, jadi tidak perlu `pip install`.
Kalau satu simbol gagal diambil, nilai lama tetap dipakai dan ditandai `lama: true`,
sehingga halaman tidak pernah kosong.
"""

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "market.json"

# kunci indikator di halaman -> simbol Yahoo Finance
INDIKATOR = {
    "ihsg": "^JKSE",
    "us10y": "^TNX",
    "dxy": "DX-Y.NYB",
    "usdidr": "IDR=X",
    "emas": "GC=F",
    "brent": "BZ=F",
}

URL = "https://query1.finance.yahoo.com/v8/finance/chart/{}?range=5d&interval=1d"
HEADERS = {"User-Agent": "Mozilla/5.0 (Meja Pantau; pemakaian pribadi)"}


def harga_kemarin(res, t_pasar):
    """Harga penutupan hari perdagangan sebelum hari harga terakhir."""
    try:
        waktu = res.get("timestamp") or []
        tutup = res["indicators"]["quote"][0]["close"]
        hari_ini = datetime.fromtimestamp(t_pasar, timezone.utc).date() if t_pasar else None
        baris = [(datetime.fromtimestamp(w, timezone.utc).date(), c) for w, c in zip(waktu, tutup) if c is not None]
        sebelum = [c for d, c in baris if hari_ini is None or d < hari_ini]
        return sebelum[-1] if sebelum else None
    except (KeyError, IndexError, TypeError):
        return None


def ambil(simbol):
    """Kembalikan {v, prev, t} untuk satu simbol, atau None kalau gagal."""
    url = URL.format(urllib.parse.quote(simbol))
    for percobaan in range(3):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.load(resp)
            res = data["chart"]["result"][0]
            meta = res["meta"]
            v = meta.get("regularMarketPrice")
            if v is None:
                return None
            t = meta.get("regularMarketTime")
            prev = harga_kemarin(res, t)
            return {
                "v": round(float(v), 4),
                "prev": round(float(prev), 4) if prev else None,
                "t": datetime.fromtimestamp(t, timezone.utc).isoformat() if t else None,
            }
        except Exception as e:  # jaringan putus, format berubah, dsb.
            print(f"  gagal {simbol} (percobaan {percobaan + 1}): {e}")
            time.sleep(2 * (percobaan + 1))
    return None


def main():
    lama = {}
    if OUT.exists():
        lama = json.loads(OUT.read_text(encoding="utf-8"))

    saham = json.loads((DATA / "saham.json").read_text(encoding="utf-8"))
    tickers = sorted({s["ticker"].upper() for s in saham})

    hasil = {"diperbarui": datetime.now(timezone.utc).isoformat(), "indikator": {}, "harga": {}}
    gagal = []

    for kunci, simbol in INDIKATOR.items():
        q = ambil(simbol)
        if q and kunci == "us10y" and q["v"] > 20:  # jaga-jaga kalau yield dikutip x10
            q["v"] = round(q["v"] / 10, 3)
            q["prev"] = round(q["prev"] / 10, 3) if q["prev"] else None
        if q:
            hasil["indikator"][kunci] = q
        else:
            gagal.append(simbol)
            sebelumnya = lama.get("indikator", {}).get(kunci)
            if sebelumnya:
                hasil["indikator"][kunci] = {**sebelumnya, "lama": True}

    for tk in tickers:
        q = ambil(f"{tk}.JK")
        if q:
            hasil["harga"][tk] = q
        else:
            gagal.append(f"{tk}.JK")
            sebelumnya = lama.get("harga", {}).get(tk)
            if sebelumnya:
                hasil["harga"][tk] = {**sebelumnya, "lama": True}

    hasil["gagal"] = gagal
    OUT.write_text(json.dumps(hasil, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    ok = len(INDIKATOR) + len(tickers) - len(gagal)
    print(f"Selesai: {ok} berhasil, {len(gagal)} gagal {gagal if gagal else ''}")


if __name__ == "__main__":
    main()
