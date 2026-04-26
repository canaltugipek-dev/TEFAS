"""Hatali fonlarin KAP disclosure sayfasinda tum ekleri (file_id'leri) listele."""
from __future__ import annotations
import sys, re, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fon_hisse_scraper import (  # noqa: E402
    _session, _kap_request, _extract_kap_obj_id, _fetch_pdr_disclosures,
    KAP_DISCLOSURE_PAGE_URL,
)

CODES = ["DHJ","IMB","IIH","IVF","HBU"]


def list_attachments(sess, disclosure_index: str):
    r = _kap_request(sess, f"{KAP_DISCLOSURE_PAGE_URL}/{disclosure_index}", timeout=45)
    if not r or not r.ok:
        return []
    text = r.text
    # Tum file_id ve etiket bilgilerini topla
    out = []
    for m in re.finditer(r"file/download/([a-f0-9]{32})", text):
        fid = m.group(1)
        # Yakin contexte etiket ariyoruz
        start = max(0, m.start()-300); end = min(len(text), m.end()+200)
        ctx = text[start:end]
        # Adi/title bul: bazi sayfalarda <span ...>BASLIK</span> seklinde
        label = None
        for lm in re.finditer(r">([^<>]{4,80})</", ctx):
            cand = lm.group(1).strip()
            if "pdf" in cand.lower() or any(w in cand.upper() for w in ("PORTFÖY", "PORTFOY", "DAGI", "DAĞI", "RAPOR", "EK", "BELGE", "PDR")):
                label = cand
                break
        out.append({"file_id": fid, "label": label})
    # uniq
    seen = set(); uniq = []
    for o in out:
        if o["file_id"] in seen: continue
        seen.add(o["file_id"]); uniq.append(o)
    return uniq


def main():
    sess = _session()
    for code in CODES:
        # disclosure listesi
        from json import loads
        data = loads((ROOT / "data" / "fon_hisse_birlesik.json").read_text(encoding="utf-8"))
        kap_link = data["fonlar"][code]["kap_link"]
        time.sleep(5)
        oid = _extract_kap_obj_id(sess, kap_link)
        if not oid:
            print(f"\n{code}: objId YOK"); continue
        time.sleep(3)
        discs = _fetch_pdr_disclosures(sess, oid)
        if not discs:
            print(f"\n{code}: disclosure YOK"); continue
        disc = discs[0]
        time.sleep(3)
        atts = list_attachments(sess, disc["disclosure_index"])
        print(f"\n========== {code}  | disclosure {disc['disclosure_index']}  ({disc.get('publish_date','')[:16]}) ==========")
        for a in atts:
            print(f"  file_id={a['file_id']}  label={a['label']!r}")


if __name__ == "__main__":
    main()
