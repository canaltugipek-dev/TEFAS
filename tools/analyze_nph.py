"""NPH detail."""
from __future__ import annotations
import re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import fon_hisse_scraper as f

text = (ROOT / "data" / "_ocr_text" / "NPH.txt").read_text(encoding="utf-8")
old = f._pdf_ocr_text
f._pdf_ocr_text = lambda b, dpi=220: text  # type: ignore[assignment]
try:
    rows = f._extract_hisse_rows_ocr(b"")
finally:
    f._pdf_ocr_text = old

total = sum(r["agirlik"] for r in rows)
print(f"NPH: {len(rows)} rows, %{total:.2f}")
for r in rows:
    print(f"  {r['ticker']:8} {r['agirlik']:6.2f}%")

ISIN_RE = re.compile(r"(TR[AE][A-Z0-9]{9})(?![A-Z0-9])")
isins = set()
for line in text.splitlines():
    for m in ISIN_RE.finditer(line):
        isins.add(m.group(1))
print(f"\nNPH ISIN count: {len(isins)}")
for li, line in enumerate(text.splitlines()):
    u = line.upper()
    if any(k in u for k in ("HISSE SENEDI", "HISSESENEDI", "TOPLAM", "FONTOPLAM", "GENEL")):
        if li < 60 or "TOPLAM" in u or "%" in line:
            print(f"  L{li+1:>3}: {line}")
