import json
from datetime import datetime, timezone

with open("data/manifest.json", "r", encoding="utf-8") as f:
    m = json.load(f)
print("guncelleme :", m.get("guncelleme"))
print("hedef_gun  :", m.get("hedef_gun"))
print("fon_sayisi :", len(m.get("fonlar") or []))

bench = m.get("benchmark") or {}
for k, v in bench.items():
    if isinstance(v, dict):
        rows = v.get("seri") or v.get("fiyatlar") or v.get("values") or v.get("rows") or []
        last_date = None
        if rows and isinstance(rows[-1], dict):
            for dk in ("tarih", "TARIH", "date", "DATE"):
                if dk in rows[-1]:
                    last_date = rows[-1][dk]
                    break
        print(f"  bench[{k}]: rows={len(rows)} last_date={last_date}")
    else:
        print(f"  bench[{k}]: {v}")

fonlar = m.get("fonlar") or []
print("durum=tam        :", sum(1 for f in fonlar if f.get("durum") == "tam"))
print("durum=veri_eksik :", sum(1 for f in fonlar if f.get("durum") == "veri_eksik"))

with open("data/MAC_tefas.json", "r", encoding="utf-8") as f:
    bundle = json.load(f)
veri = bundle.get("veri") or []
print(f"MAC: kayit={len(veri)} baslangic={bundle.get('baslangic')} bitis={bundle.get('bitis')}")
if veri:
    first = veri[0]
    last = veri[-1]
    def to_iso(epoch_ms_str):
        try:
            return datetime.fromtimestamp(int(epoch_ms_str) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        except Exception:
            return epoch_ms_str
    print(f"  ilk: {to_iso(first.get('TARIH'))} -> {first.get('FIYAT')}")
    print(f"  son: {to_iso(last.get('TARIH'))} -> {last.get('FIYAT')}")
