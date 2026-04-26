"""NKT lo-res ve hires OCR'da hangi ISIN'ler var, hangileri parse edildi."""
from __future__ import annotations
import re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import fon_hisse_scraper as f  # noqa: E402

_ISIN_SUBSTR = re.compile(r"(TR[AE][A-Z0-9]{9})(?![A-Z0-9])")

for src in ["NKT.txt", "NKT_hires.txt"]:
    p = ROOT / "data" / "_ocr_text" / src
    if not p.exists():
        continue
    text = p.read_text(encoding="utf-8")
    isins = set()
    for line in text.splitlines():
        for m in _ISIN_SUBSTR.finditer(line):
            isins.add(m.group(1))
    # Parse
    old = f._pdf_ocr_text
    f._pdf_ocr_text = lambda b, dpi=220: text  # type: ignore[assignment]
    try:
        rows = f._extract_hisse_rows_ocr(b"")
    finally:
        f._pdf_ocr_text = old

    parsed = {r["ticker"] for r in rows}
    total = sum(r["agirlik"] for r in rows)
    print(f"\n=== {src} ===")
    print(f"  OCR'da {len(isins)} unique stock ISIN, parser {len(rows)} row, toplam %{total:.2f}")
    print(f"  ISINS: {sorted(isins)}")
    print(f"  PARSED tickers: {sorted(parsed)}")
    # Hangi ISIN'ler var ama parse edilmemis?
    for isin in sorted(isins):
        body = isin[3:]
        # body 4/5 char alpha prefix
        for tlen in (5, 4):
            pref = body[:tlen]
            if re.match(r"^[A-Z]+$", pref):
                # parsed icinde herhangi bir ticker bu ISIN'e eslesti mi?
                if any(t in pref or pref in t for t in parsed):
                    break
        else:
            print(f"  EKSIK? ISIN={isin} body={body}")
