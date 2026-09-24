"""Uji aturan entry / cut loss / take profit pada data historis (backtest).

Memakai fungsi `setup_teknikal` yang SAMA dengan robot harian, dijalankan hari demi hari
pada data 2 tahun terakhir untuk semua saham di data/peta.json.

Jalankan:  python3 scripts/backtest.py
Hasil:     data/backtest.json (ditampilkan di halaman) + ringkasan di layar.

Asumsi simulasi (sengaja konservatif):
- Logika order dan exit memakai `jalankan_posisi` yang sama dengan jurnal harian.
- Sinyal muncul saat penutupan hari T. Order beli berlaku 5 hari bursa berikutnya.
- Terisi kalau harga turun ke batas atas area entry (atau dibuka di bawahnya).
  Kalau dibuka di bawah cut loss, order dibatalkan.
- Setelah terisi: kena cut loss kalau harga terendah <= cut loss (gap turun = keluar di harga pembukaan).
  Kalau cut loss dan target tersentuh di hari yang sama, dianggap kena cut loss.
- Varian A: jual semua di TP1.
  Varian B: jual separuh di TP1, sisanya di TP2; setelah TP1 cut loss dipindah ke harga beli.
- Maksimal ditahan 20 hari bursa, lalu dijual di harga penutupan.
- Biaya: beli 0,15%, jual 0,25%. Satu posisi per saham pada satu waktu.
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from update_market import DATA, ambil, hasil_bersih, jalankan_posisi, konteks_pasar, setup_teknikal  # noqa: E402

PEMANASAN = 60


def pasar_harian(baris_ihsg):
    """Fungsi tanggal -> konteks_pasar IHSG pada tanggal itu (tanpa melihat masa depan)."""
    tgl = [datetime.fromtimestamp(b["t"], timezone.utc).date() for b in baris_ihsg]
    cache = {}

    def cari(ts):
        d = datetime.fromtimestamp(ts, timezone.utc).date()
        if d not in cache:
            i = max((j for j, x in enumerate(tgl) if x <= d), default=None)
            cache[d] = konteks_pasar(baris_ihsg[: i + 1]) if i is not None else None
        return cache[d]
    return cari


def simulasi(baris, pasar_fn=None, saring=None):
    """Kembalikan daftar transaksi untuk satu saham.

    pasar_fn(timestamp) -> konteks pasar pada hari itu (filter IHSG & kekuatan relatif).
    saring(baris, t, s) -> bool: filter tambahan untuk eksperimen.
    """
    c = [b["c"] for b in baris]
    hasil = []
    t = PEMANASAN
    while t < len(baris) - 1:
        s = setup_teknikal(baris[: t + 1], c[t], pasar_fn(baris[t]["t"]) if pasar_fn else None)
        if s.get("setup") != "pullback" or (saring and not saring(baris, t, s)):
            t += 1
            continue
        args = (baris, t + 1, s["entry"][1], s["cl"], s["tp1"], s["tp2"])
        hasil_ab = {"A": jalankan_posisi(*args, bagi_dua=False), "B": jalankan_posisi(*args, bagi_dua=True)}
        r = hasil_ab["B"]
        if r["status"] in ("batal", "menunggu"):
            t += 1
            continue
        if "jual" not in r or "jual" not in hasil_ab["A"]:
            break  # posisi masih terbuka di akhir data: tidak dihitung
        risiko = r["beli"] - s["cl"]
        catatan = {"setup": s["setup"], "tanggal": datetime.fromtimestamp(baris[t]["t"], timezone.utc).date().isoformat(),
                   "beli": round(r["beli"], 1), "cl": s["cl"], "tp1": s["tp1"], "tp2": s["tp2"]}
        for nama, x in hasil_ab.items():
            catatan[nama] = {"hasil": x["status"], "pct": round(hasil_bersih(x["beli"], x["jual"]) * 100, 2),
                             "R": round((x["jual"] - x["beli"]) / risiko, 2), "hari": x["keluar"] - x["isi"] + 1}
        hasil.append(catatan)
        t = max(x["keluar"] for x in hasil_ab.values()) + 1  # satu posisi per saham
    return hasil


def ringkas(transaksi, varian):
    if not transaksi:
        return {"n": 0}
    x = [tr[varian] for tr in transaksi]
    pct = [a["pct"] for a in x]
    untung = [p for p in pct if p > 0]
    rugi = [p for p in pct if p <= 0]
    return {
        "n": len(x),
        "menang_pct": round(len(untung) / len(x) * 100, 1),
        "rata_pct": round(sum(pct) / len(x), 2),
        "rata_R": round(sum(a["R"] for a in x) / len(x), 2),
        "profit_factor": round(sum(untung) / abs(sum(rugi)), 2) if rugi and sum(rugi) else None,
        "rata_hari": round(sum(a["hari"] for a in x) / len(x), 1),
        "cut_loss": sum(1 for a in x if a["hasil"] == "cut loss"),
    }


def paruh(transaksi):
    """Hasil varian B di paruh pertama vs kedua periode: cek apakah hasilnya konsisten."""
    if not transaksi:
        return {}
    tgl = sorted(t["tanggal"] for t in transaksi)
    belah = tgl[len(tgl) // 2]
    return {"belah": belah,
            "awal": ringkas([t for t in transaksi if t["tanggal"] < belah], "B"),
            "akhir": ringkas([t for t in transaksi if t["tanggal"] >= belah], "B")}


def main():
    peta = json.loads((DATA / "peta.json").read_text(encoding="utf-8"))
    tema_saham = {k: v["saham"] for k, v in peta["tema"].items()}
    kode = sorted({s for daftar in tema_saham.values() for s in daftar})

    ihsg = ambil("^JKSE", "2y")
    pasar_fn = pasar_harian(ihsg["baris"]) if ihsg else None
    semua, per_saham = [], {}
    for i, tk in enumerate(kode, 1):
        data = ambil(f"{tk}.JK", "2y")
        time.sleep(0.3)
        if not data:
            print(f"  lewati {tk}: data tidak tersedia")
            continue
        tr = simulasi(data["baris"], pasar_fn)
        for x in tr:
            x["saham"] = tk
        semua += tr
        per_saham[tk] = tr
        print(f"  [{i}/{len(kode)}] {tk}: {len(tr)} transaksi")

    ihsg_pct = None
    if ihsg and ihsg["baris"]:
        ihsg_pct = round((ihsg["baris"][-1]["c"] / ihsg["baris"][PEMANASAN]["c"] - 1) * 100, 1)

    hasil = {
        "dibuat": datetime.now(timezone.utc).isoformat(),
        "periode": "2 tahun terakhir (60 hari pertama untuk pemanasan indikator)",
        "asumsi": "Order berlaku 5 hari; cut loss diutamakan kalau bersamaan dengan target; maks. 20 hari; biaya beli 0,15% + jual 0,25%.",
        "ihsg_pct": ihsg_pct,
        "semua": {"A": ringkas(semua, "A"), "B": ringkas(semua, "B")},
        "paruh": paruh(semua),
        "per_tema": {k: {"label": peta["tema"][k]["label"],
                         "A": ringkas([t for t in semua if t["saham"] in v], "A"),
                         "B": ringkas([t for t in semua if t["saham"] in v], "B")} for k, v in tema_saham.items()},
        "per_saham": {k: {"A": ringkas(v, "A"), "B": ringkas(v, "B")} for k, v in per_saham.items()},
    }
    (DATA / "backtest.json").write_text(json.dumps(hasil, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    def baris(nama, r):
        if not r.get("n"):
            return f"{nama:<28} -"
        pf = r["profit_factor"] if r["profit_factor"] is not None else "-"
        return (f"{nama:<28} n={r['n']:<4} menang={r['menang_pct']:>5}%  rata={r['rata_pct']:>6}%  "
                f"R={r['rata_R']:>5}  PF={pf}  hari={r['rata_hari']}")

    print("\n=== SEMUA ===")
    for v in "AB":
        print(baris(f"Varian {v}", hasil["semua"][v]))
    print("\n=== PER TEMA (varian B) ===")
    for k, r in hasil["per_tema"].items():
        print(baris(r["label"], r["B"]))
    print(f"\nIHSG pada periode yang sama: {ihsg_pct}%")


if __name__ == "__main__":
    main()
