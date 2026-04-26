"""Cached OCR text uzerinde sadece parser'i test et (RapidOCR'i tekrar kosturma).

PARSE LOGIC: production fon_hisse_scraper._extract_hisse_rows_ocr (tek source of truth).
Burada sadece _pdf_ocr_text fonksiyonunu cached text dondurecek sekilde monkey-patch
ediyoruz, boylece prod kod path'inden gecmis olur.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import fon_hisse_scraper as f  # noqa: E402

OUT = ROOT / "data" / "_ocr_text"


def parse_text(text: str) -> list[dict]:
    old = f._pdf_ocr_text
    f._pdf_ocr_text = lambda b, dpi=220: text  # type: ignore[assignment]
    try:
        return f._extract_hisse_rows_ocr(b"")
    finally:
        f._pdf_ocr_text = old


files = ["DTH", "NKT", "NKT_hires", "NLE", "NPH", "SUR"]
for code in files:
    p = OUT / f"{code}.txt"
    if not p.exists():
        continue
    text = p.read_text(encoding="utf-8")
    rows = parse_text(text)
    total = sum(r["agirlik"] for r in rows)
    print(f"\n{code:10}  rows={len(rows):>3}  toplam={total:6.2f}%")
    for r in rows:
        print(f"   {r['ticker']:8} {r['agirlik']:7.4f}%")
