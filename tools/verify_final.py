"""fon_hisse_birlesik.json son durumu dogrulama."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
d = json.loads((ROOT / "data" / "fon_hisse_birlesik.json").read_text(encoding="utf-8"))
fons = d["fonlar"]
print(f"Toplam fon: {len(fons)}")
ok = sum(1 for f in fons.values() if (f.get("hisse_durumu") or "") == "ok")
hk = sum(1 for f in fons.values() if (f.get("hisse_durumu") or "") == "hisse_yogun_degil")
fail = sum(1 for f in fons.values() if (f.get("hisse_durumu") or "") not in ("ok", "hisse_yogun_degil"))
print(f"OK: {ok}, hisse_yogun_degil: {hk}, hata: {fail}")

print("\nImage-only fonlar (OCR ile cozulduler):")
for code in ["DTH", "NKT", "NLE", "NPH", "SUR"]:
    b = fons.get(code) or {}
    rows = b.get("hisseler") or []
    tot = sum(h.get("agirlik", 0) for h in rows)
    durum = b.get("hisse_durumu")
    rt = b.get("kap_rapor_tarihi")
    print(f"  {code:5}  durum={durum:10}  rows={len(rows):>3}  toplam={tot:6.2f}%  rapor={rt}")
    if rows:
        for h in rows[:5]:
            print(f"     - {h['ticker']:8} {h['agirlik']:6.2f}%  {h.get('ad','')[:40]}")
