"""Yanlis raporu donen fonlarin disclosure listesini detayli incele."""
from __future__ import annotations
import sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fon_hisse_scraper import _session, _extract_kap_obj_id, _fetch_pdr_disclosures, _kap_request, KAP_DISCLOSURE_FILTER_URL  # noqa: E402

CODES = ["DHJ","IMB","IIH","IVF","HBU","DTH","NKT","NLE","NPH","RBH","SUR","TZD","ZHH","ZJL","ZJV","ZLH","ZPE"]
data = json.loads((ROOT / "data" / "fon_hisse_birlesik.json").read_text(encoding="utf-8"))

sess = _session()
import time
for code in CODES:
    fon = data["fonlar"][code]
    kap_link = fon.get("kap_link")
    print(f"\n========== {code} ==========")
    print(f"  kap_link: {kap_link}")
    oid = _extract_kap_obj_id(sess, kap_link)
    print(f"  objId: {oid}")
    if not oid:
        time.sleep(3); continue
    discs = _fetch_pdr_disclosures(sess, oid)
    print(f"  disclosure sayisi: {len(discs)}")
    for i, d in enumerate(discs[:5]):
        print(f"    [{i}] {d.get('publish_date','')[:16]:<18} | "
              f"period={d.get('period','-')!s:<8} | title={(d.get('title') or '')[:80]}")
    time.sleep(1.5)
