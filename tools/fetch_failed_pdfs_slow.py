"""Yavas + cookie-li PDF indirme - rate-limit'e takilmamak icin.
Tum 17 fonun PDF'sini indirir, onceden indirilenleri atlar."""
from __future__ import annotations
import sys, time, json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from fon_hisse_scraper import (  # noqa: E402
    _session, _extract_kap_obj_id, _fetch_pdr_disclosures,
    _fetch_file_id_from_disclosure_page, _download_kap_pdf,
)

OUT = ROOT / "data" / "_failed_pdfs"
OUT.mkdir(parents=True, exist_ok=True)
META = OUT / "_meta.json"

CODES = ["DHJ","IMB","IIH","IVF","HBU","DTH","NKT","NLE","NPH","RBH","SUR","TZD","ZHH","ZJL","ZJV","ZLH","ZPE"]


def main():
    data = json.loads((ROOT / "data" / "fon_hisse_birlesik.json").read_text(encoding="utf-8"))
    sess = _session()
    meta: dict = json.loads(META.read_text("utf-8")) if META.is_file() else {}

    for code in CODES:
        out_pdf = OUT / f"{code}.pdf"
        if out_pdf.is_file() and out_pdf.stat().st_size > 1024:
            print(f"[{code}] zaten var ({out_pdf.stat().st_size} bytes), atlandi")
            continue
        kap_link = data["fonlar"][code].get("kap_link")
        print(f"\n[{code}] -> indirilmeye baslaniyor")
        time.sleep(8)

        oid = None
        for attempt in range(4):
            oid = _extract_kap_obj_id(sess, kap_link)
            if oid:
                break
            wait = 8 * (attempt + 1)
            print(f"  objId yok, {wait}s bekleyip tekrar...")
            time.sleep(wait)
        if not oid:
            print(f"  [{code}] objId bulunamadi, atlandi")
            continue
        print(f"  objId: {oid}")
        time.sleep(4)

        discs = _fetch_pdr_disclosures(sess, oid)
        if not discs:
            print(f"  [{code}] disclosure yok, atlandi")
            continue
        disc = discs[0]
        print(f"  disclosure: {disc.get('publish_date','')} | {(disc.get('title') or '')[:50]}")
        time.sleep(4)

        fid = _fetch_file_id_from_disclosure_page(sess, disc["disclosure_index"])
        if not fid:
            print(f"  [{code}] file_id yok, atlandi")
            continue
        print(f"  file_id: {fid}")
        time.sleep(4)

        pdf = _download_kap_pdf(sess, fid)
        if not pdf:
            print(f"  [{code}] PDF indirilemedi")
            continue
        out_pdf.write_bytes(pdf)
        try:
            doc = pymupdf.open(stream=pdf, filetype="pdf")
            text = "".join(p.get_text("text") for p in doc)
            tlen = len(text.strip())
            pages = len(doc)
        except Exception as e:
            tlen, pages = 0, 0
            print(f"  parse fail: {e}")
        meta[code] = {
            "size": len(pdf), "pages": pages, "text_len": tlen,
            "title": disc.get("title"),
            "publish_date": disc.get("publish_date"),
            "file_id": fid, "obj_id": oid,
        }
        META.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  -> {out_pdf} (size={len(pdf)}, pages={pages}, text={tlen})")


if __name__ == "__main__":
    main()
