"""_known_tickers.txt'i SADECE OCR-disi fonlardan yeniden olustur.

OCR yanlis-pozitif ticker'lari (TNZTP, EDIPE, TUPRA, ...) known set'e sizmasi
icin: image-only (OCR ile islenmis) fonlari haric tut.
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# OCR ile islenen 5 image-only fon (sirasiyla cikarilacak):
OCR_FUNDS = {"DTH", "NKT", "NLE", "NPH", "SUR"}

with open(ROOT / "data" / "fon_hisse_birlesik.json", encoding="utf-8") as fh:
    data = json.load(fh)

tickers: set[str] = set()
ocr_only: set[str] = set()
for kod, f in data["fonlar"].items():
    for h in f.get("hisseler", []):
        t = h["ticker"]
        if kod in OCR_FUNDS:
            ocr_only.add(t)
        else:
            tickers.add(t)

# OCR-only kaynaktan gelip text-tabanli kaynaktan gelmeyen ticker'lar suspheli
suspicious = ocr_only - tickers
print(f"text-tabanli benzersiz: {len(tickers)}")
print(f"OCR-only benzersiz:     {len(ocr_only)}")
print(f"Sadece OCR'da goren (suspheli): {sorted(suspicious)}")

out = sorted(tickers)
(ROOT / "data" / "_known_tickers.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
print(f"\nyazildi: {len(out)} text-tabanli ticker -> data/_known_tickers.txt")
