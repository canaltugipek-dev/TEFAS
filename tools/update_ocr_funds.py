"""5 OCR fonunu (DTH/NKT/NLE/NPH/SUR) cached PDF'den parse edip
fon_hisse_birlesik.json'daki hisseler listelerini guncelle.
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import fon_hisse_scraper as f  # noqa: E402

OCR_FUNDS = ["DTH", "NKT", "NLE", "NPH", "SUR"]
PDF_DIR = ROOT / "data" / "_failed_pdfs"
DB_PATH = ROOT / "data" / "fon_hisse_birlesik.json"


def main() -> None:
    db = json.loads(DB_PATH.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for code in OCR_FUNDS:
        pdf = PDF_DIR / f"{code}.pdf"
        if not pdf.exists():
            print(f"[!] {code}: PDF yok, atliyorum")
            continue
        raw = pdf.read_bytes()
        ocr_pdf = bool(f._pdf_is_image_only(raw))
        result = f.extract_hisse_rows_from_pdr_pdf(raw)
        rows, err = result if isinstance(result, tuple) else (result, None)
        if not rows:
            print(f"[!] {code}: parser sonuc dondurmedi ({err})")
            continue
        total = sum(r["agirlik"] for r in rows)
        ent = db["fonlar"].get(code)
        if ent is None:
            print(f"[!] {code}: db'de yok")
            continue
        # Hisseler listesini guncelle - 'ad' bos string birak (mevcut sema)
        ent["hisseler"] = [
            {"ticker": r["ticker"], "ad": "", "agirlik": round(r["agirlik"], 2)}
            for r in rows
        ]
        ent["guncelleme"] = now
        if ocr_pdf:
            ent["kaynak_pdr_ocr"] = True
        else:
            ent.pop("kaynak_pdr_ocr", None)
        print(f"[OK] {code:4} rows={len(rows):>3} toplam=%{total:6.2f}")

    db["guncelleme"] = now
    DB_PATH.write_text(
        json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n=> Yazildi: {DB_PATH}")


if __name__ == "__main__":
    main()
