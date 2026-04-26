"""Pass 2'yi izle (TNZTP nereden geliyor?)"""
from __future__ import annotations
import re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import fon_hisse_scraper as f  # noqa: E402

# Production parser kullanalim
text = (ROOT / "data" / "_ocr_text" / "NKT.txt").read_text(encoding="utf-8")

# pdf_bytes degil text alir; biz dogrudan _extract_hisse_rows_ocr'u manipule edelim.
# fonk text uzerinden calisir.
import inspect
src = inspect.getsource(f._extract_hisse_rows_ocr)
# print(src[:1500])

# patch: rapidocr atla, dogrudan text uretelim
def fake_pdf_ocr(b, dpi=220): return text
old = f._pdf_ocr_text
f._pdf_ocr_text = fake_pdf_ocr
try:
    rows = f._extract_hisse_rows_ocr(b"")
    print(f"Toplam: {len(rows)} satir")
    print(f"Top by%: {[(r['ticker'], r['agirlik']) for r in rows]}")
    has_tnztp = [r for r in rows if r['ticker']=='TNZTP']
    has_tapd = [r for r in rows if r['ticker']=='TAPD']
    print(f"TNZTP: {has_tnztp}")
    print(f"TAPD:  {has_tapd}")
finally:
    f._pdf_ocr_text = old
