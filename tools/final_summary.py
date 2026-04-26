"""Tum data dosyalarinin son durumunu ozetler."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

print("=" * 70)
print("TEFAS PROJESI - VERI GUNCELLEME OZETI")
print("=" * 70)

# 1. Manifest
data = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
print(f"\n[manifest.json]")
print(f"  guncelleme: {data.get('guncelleme')}")
fonlar = data.get("fonlar", [])
print(f"  fon adedi: {len(fonlar)}")
eksik = sum(1 for f in fonlar if f.get("eksik"))
print(f"  tam veri: {len(fonlar) - eksik}, eksik: {eksik}")

# 2. Benchmark
bdata = json.loads((DATA / "benchmarks.json").read_text(encoding="utf-8"))
print(f"\n[benchmarks.json]")
print(f"  guncelleme: {bdata.get('guncelleme')}")
for b in bdata.get("benchmarks", []):
    rows = b.get("historical") or b.get("rows") or b.get("seri") or []
    last = rows[-1] if rows else None
    name = b.get("id") or b.get("kod") or b.get("name") or "?"
    last_t = last.get("tarih") if isinstance(last, dict) else "YOK"
    print(f"  {name:20} son tarih: {last_t}")

# 3. fon_hisse_birlesik
khdata = json.loads((DATA / "fon_hisse_birlesik.json").read_text(encoding="utf-8"))
fns = khdata.get("fonlar") or {}
ok = sum(1 for v in fns.values() if v["hisse_durumu"] == "ok")
print(f"\n[fon_hisse_birlesik.json] (KAP PDR)")
print(f"  guncelleme: {khdata.get('guncelleme')}")
print(f"  toplam: {len(fns)}  OK: {ok}  Hata: {len(fns) - ok}")
ns = [len(v["hisseler"]) for v in fns.values() if v["hisse_durumu"] == "ok"]
if ns:
    print(f"  OK fonlarda toplam {sum(ns)} hisse satiri (ortalama {sum(ns)/len(ns):.1f}/fon)")

# 4. Bireysel fon json'lari
tefas_files = list(DATA.glob("*_tefas.json"))
hisse_files = list(DATA.glob("*_hisse_pdr.json"))
print(f"\n[Bireysel JSON dosyalari]")
print(f"  *_tefas.json: {len(tefas_files)} dosya")
print(f"  *_hisse_pdr.json: {len(hisse_files)} dosya")

# Ornek bir fonun en son veri tarihi
if tefas_files:
    sample = json.loads(tefas_files[0].read_text(encoding="utf-8"))
    rows = sample.get("rows") or []
    if rows:
        print(f"  Ornek ({tefas_files[0].stem}): son tarih {rows[-1].get('tarih')}")
