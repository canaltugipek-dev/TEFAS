"""NKT OCR'da hangi entry'ler atlanmis analiz et."""
from __future__ import annotations
import re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import fon_hisse_scraper as f  # noqa: E402

text = (ROOT / "data" / "_ocr_text" / "NKT.txt").read_text(encoding="utf-8")
lines = text.splitlines()

# OCR'daki TUM ISIN substring'lerini bul (TRA/TRE prefix), satir + konum
_ISIN_INLINE = re.compile(r"(TR[AE][A-Z0-9]{9})(?![A-Z0-9])")
isins_in_text = []
for li, line in enumerate(lines):
    for m in _ISIN_INLINE.finditer(line):
        isins_in_text.append((li, m.start(), m.group(1), line))

print(f"NKT OCR'da bulunan ISIN sayisi: {len(isins_in_text)}")
print(f"Parser'in ciktisi (25 row):\n")

# Parser'i tekrar koş
import importlib
sys.path.insert(0, str(ROOT / "tools"))
import test_ocr_cached as t
importlib.reload(t)
rows = t.parse_text(text)
parsed_tickers = {r["ticker"] for r in rows}
print(f"  Parsed: {sorted(parsed_tickers)}\n")

# Her ISIN icin: parser tarafindan yakalandi mi?
print(f"\nOCR'daki tum ISIN listesi (line, isin, baglam):")
for li, col, isin, line in isins_in_text:
    body = isin[3:]  # 9 char body
    # ticker tahmini (5 char prefix)
    ctx = line[max(0, col-30): col+12 + 30]
    print(f"  L{li+1:>3}: {isin}  body={body}  ...{ctx[-60:]}")
