"""Kalan 17 basarisiz fonu icin PDF'leri indir + format sinifa ayir.
Sonuc: data/_failed_pdfs/{KOD}.pdf + format_classification.json"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from fon_hisse_scraper import (  # noqa: E402
    _session,
    _extract_kap_obj_id,
    _fetch_pdr_disclosures,
    _fetch_file_id_from_disclosure_page,
    _download_kap_pdf,
)

OUT_DIR = ROOT / "data" / "_failed_pdfs"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def classify(text: str) -> str:
    if not text or len(text.strip()) < 20:
        return "image_only"
    t = text.upper()
    # Ziraat 'AYLIK RAPOR' format
    if "AYLIK RAPOR" in t and "FONU TANITICI BILGILER" in t.replace("İ", "I"):
        return "ziraat_aylik"
    # 'VII-PORTFOYDEN SATISLAR' format (PDF basinda satis tablosu)
    if "PORTF" in t and ("SATI" in t and "VII" in text):
        return "satislar_format"
    return "unknown"


def main():
    data = json.loads((ROOT / "data" / "fon_hisse_birlesik.json").read_text(encoding="utf-8"))
    fonlar = data["fonlar"]
    failed = sorted(
        kod for kod, v in fonlar.items()
        if (v.get("hisse_durumu") or "bulunamadi") != "ok"
    )
    print(f"Basarisiz fon sayisi: {len(failed)}")
    print(f"Liste: {failed}\n")

    sess = _session()
    classification = {}
    for code in failed:
        block = fonlar.get(code) or {}
        kap_link = block.get("kap_link")
        if not kap_link:
            print(f"{code:5} | kap_link YOK"); continue
        oid = _extract_kap_obj_id(sess, kap_link)
        if not oid:
            print(f"{code:5} | objId YOK"); continue
        discs = _fetch_pdr_disclosures(sess, oid)
        if not discs:
            print(f"{code:5} | disclosure YOK"); continue
        disc = discs[0]
        fid = _fetch_file_id_from_disclosure_page(sess, disc["disclosure_index"])
        if not fid:
            print(f"{code:5} | file_id YOK"); continue
        pdf = _download_kap_pdf(sess, fid)
        if not pdf:
            print(f"{code:5} | PDF download FAIL"); continue
        out = OUT_DIR / f"{code}.pdf"
        out.write_bytes(pdf)

        try:
            doc = pymupdf.open(stream=pdf, filetype="pdf")
            full = "".join(p.get_text("text") + "\n" for p in doc)
        except Exception as e:
            print(f"{code:5} | PDF parse FAIL: {e}"); continue
        cls = classify(full)
        classification[code] = {
            "size": len(pdf),
            "pages": len(doc),
            "text_len": len(full.strip()),
            "format": cls,
            "disc_date": disc.get("publish_date"),
            "title": disc.get("title", "")[:50],
        }
        print(f"{code:5} | size={len(pdf):>8} pages={len(doc):>2} text={len(full.strip()):>6} | {cls:18} | {disc.get('publish_date', '')[:16]}")

    (ROOT / "data" / "_failed_classification.json").write_text(
        json.dumps(classification, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("\n=== ozet ===")
    by_cat = {}
    for code, info in classification.items():
        by_cat.setdefault(info["format"], []).append(code)
    for cat, codes in sorted(by_cat.items()):
        print(f"  {cat}: {len(codes)}  ->  {codes}")


if __name__ == "__main__":
    main()
