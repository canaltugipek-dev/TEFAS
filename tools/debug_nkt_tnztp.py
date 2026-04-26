"""TNZTP'nin parser'da hangi adimda atandigini izle."""
from __future__ import annotations
import re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import fon_hisse_scraper as f  # noqa: E402

text = (ROOT / "data" / "_ocr_text" / "NKT.txt").read_text(encoding="utf-8")
lines = text.splitlines()

_ISIN_SUBSTR = re.compile(r"(TR[AE][A-Z0-9]{9})(?![A-Z0-9])")
KNOWN = f._get_known_tickers()
print(f"KNOWN size: {len(KNOWN)}")
print(f"TNZTP in KNOWN: {'TNZTP' in KNOWN}")
print(f"TAPD in KNOWN: {'TAPD' in KNOWN}")

def _ocr_to_pct(s):
    if not f._OCR_PCT_RE.match(s): return None
    try: v = float(s.replace(",","."))
    except ValueError: return None
    if 0 < v <= 50: return v
    return None

def pct_candidates(tokens):
    return [p for t in tokens if (p := _ocr_to_pct(t)) is not None]

# Pass1 simulation
rows = {}
for li, line in enumerate(lines):
    toks = line.split()
    if not toks: continue
    isin_idx = None
    for i, t in enumerate(toks):
        if f._OCR_STOCK_ISIN_RE.match(t):
            isin_idx = i; break
        m = _ISIN_SUBSTR.search(t)
        if m and m.end() >= len(t)-1:
            isin_idx = i; break
    if isin_idx is None: continue
    # Just record
    pcts = pct_candidates(toks[isin_idx+1:])
    if not pcts and li+1 < len(lines):
        pcts = pct_candidates(lines[li+1].split())
    if not pcts: continue
    if "TNZTP" in line or "TAPDi" in line or "TAPD" in line.upper():
        print(f"  Pass1 line {li+1}: '{line}'")
        print(f"    pcts={pcts}")

# Pass2 simulation: which lines pick TNZTP in pass2?
print("\n\n=== Pass 2 (ISIN-less fallback) ===")
seen_tickers = set()  # Pretend rows_by_ticker is empty
for li, line in enumerate(lines):
    toks = line.split()
    if not toks: continue
    if any(f._OCR_STOCK_ISIN_RE.match(t) for t in toks): continue
    if any((mz := _ISIN_SUBSTR.search(t)) and mz.end() >= len(t)-1 for t in toks): continue
    for tk in toks[:2]:
        tk2 = tk.strip(":,;()")
        if tk2 == "TNZTP":
            pcts_here = pct_candidates(toks)
            print(f"  TNZTP found at line {li+1}: '{line}'")
            print(f"    pcts_here on this line = {pcts_here}")
            if li+1 < len(lines):
                nxt = lines[li+1].split()
                pcts_next = pct_candidates(nxt)
                print(f"    next line {li+2}: '{lines[li+1]}'")
                print(f"    pcts_next = {pcts_next}")
