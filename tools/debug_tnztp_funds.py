"""TNZTP iceren 4 fonu detayli incele - gercek ticker mi?"""
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
d = json.load(open(ROOT / "data" / "fon_hisse_birlesik.json", encoding="utf-8"))
for kod in ["ACC", "BIY", "NUH", "PHI"]:
    f = d["fonlar"][kod]
    print(f"\n=== {kod} ===  (toplam {len(f.get('hisseler',[]))} hisse, "
          f"%{sum(h['agirlik'] for h in f.get('hisseler',[])):.2f})")
    print(f"  fon_adi: {f.get('ad','?')}")
    for h in sorted(f.get("hisseler", []), key=lambda x: -x["agirlik"])[:8]:
        print(f"  {h['ticker']:<8}  {h['agirlik']:>6.2f}%")
