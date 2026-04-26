"""NPH ISIN vs parsed mapping."""
from __future__ import annotations
import re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import fon_hisse_scraper as f

text = (ROOT / "data" / "_ocr_text" / "NPH.txt").read_text(encoding="utf-8")
ISIN_RE = re.compile(r"(TR[AE][A-Z0-9]{9})(?![A-Z0-9])")
lines = text.splitlines()
isins_with_line = []
for li, line in enumerate(lines):
    for m in ISIN_RE.finditer(line):
        isins_with_line.append((li + 1, m.group(1), line))

print(f"OCR ISIN'leri ({len(isins_with_line)}):")
for li, isin, line in isins_with_line:
    print(f"  L{li:>3}: {isin}  ({line[:70]}...)")
