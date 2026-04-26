"""5 image-only PDF'in OCR metnini diske yaz. False positive analizi icin."""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fon_hisse_scraper import _pdf_ocr_text  # noqa: E402

PDFS = ROOT / "data" / "_failed_pdfs"
OUT = ROOT / "data" / "_ocr_text"
OUT.mkdir(parents=True, exist_ok=True)

for code in ["DTH", "NKT", "NLE", "NPH", "SUR"]:
    p = PDFS / f"{code}.pdf"
    if not p.is_file(): continue
    print(f"OCR {code}...", flush=True)
    txt = _pdf_ocr_text(p.read_bytes())
    (OUT / f"{code}.txt").write_text(txt, encoding="utf-8")
    print(f"  -> {len(txt)} chars")
