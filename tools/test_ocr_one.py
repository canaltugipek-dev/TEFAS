"""Tek bir image-only PDF'de OCR ardindan parser test et."""
from __future__ import annotations
import sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fon_hisse_scraper import extract_hisse_rows_from_pdr_pdf, _pdf_ocr_text  # noqa: E402

CANDIDATES = ["DTH"]
PDFS = ROOT / "data" / "_failed_pdfs"

for code in CANDIDATES:
    p = PDFS / f"{code}.pdf"
    pdf = p.read_bytes()
    t0 = time.time()
    print(f"========== {code} ==========")
    text = _pdf_ocr_text(pdf, dpi=200)
    print(f"OCR: {time.time()-t0:.1f}s, text_len={len(text)}")
    out_dir = ROOT / "data"
    (out_dir / f"_ocr_{code}.txt").write_text(text, encoding="utf-8")
    print(f"yazildi: {out_dir / f'_ocr_{code}.txt'}")
