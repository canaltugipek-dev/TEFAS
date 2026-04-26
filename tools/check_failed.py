import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
data = json.loads((ROOT / "data" / "fon_hisse_birlesik.json").read_text(encoding="utf-8"))
fonlar = data["fonlar"]
fail = [(k, v) for k, v in fonlar.items() if v["hisse_durumu"] != "ok"]
total_fail = len(fail)
with_kaplink = sum(1 for _, v in fail if v.get("kap_link"))
print(f"Basarisiz: {total_fail}, kap_link var: {with_kaplink}, yok: {total_fail - with_kaplink}")
print("--- 6 ornek ---")
for k, v in fail[:6]:
    kl = (v.get("kap_link") or "")[:80]
    print(f"  {k:5} durum={v['hisse_durumu']:13} mesaj={v['hisse_mesaj']:42} kap_link={kl}")
