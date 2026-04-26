"""NKT PDF'i daha yuksek DPI ile yeniden OCR et."""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import fon_hisse_scraper as f  # noqa: E402

pdf = (ROOT / "data" / "_failed_pdfs" / "NKT.pdf").read_bytes()

# 350 DPI hires
text = f._pdf_ocr_text(pdf, dpi=350)
out_path = ROOT / "data" / "_ocr_text" / "NKT_hires.txt"
out_path.write_text(text, encoding="utf-8")
print(f"Yazildi: {out_path}  ({len(text)} chars)")
