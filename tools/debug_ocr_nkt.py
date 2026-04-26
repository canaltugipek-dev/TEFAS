"""NKT'de BIMAS'in 6.98 yerine 8.45 cikmasini debug et."""
from __future__ import annotations
import re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import fon_hisse_scraper as f  # noqa: E402

text = (ROOT / "data" / "_ocr_text" / "NKT.txt").read_text(encoding="utf-8")

_ISIN_SUBSTR = re.compile(r"(TR[AE][A-Z0-9]{9})(?![A-Z0-9])")
KNOWN = f._get_known_tickers()


def first_valid(tokens):
    for tk in tokens:
        tk = tk.strip(":,;()")
        if f._OCR_TICKER_RE.match(tk) and tk not in f._TICKER_BLACKLIST and tk not in f._OCR_WORD_BLACKLIST:
            return tk
    return None


def fused_extract(prefix):
    if not prefix or not prefix[0].isalpha(): return None
    cands = []
    for tlen in (5, 4, 6, 3):
        if len(prefix) <= tlen: continue
        c = prefix[:tlen]
        if f._OCR_TICKER_RE.match(c) and c not in f._TICKER_BLACKLIST and c not in f._OCR_WORD_BLACKLIST:
            cands.append(c)
    if not cands: return None
    if KNOWN:
        for c in cands:
            if c in KNOWN: return c
    return cands[0]


lines = text.splitlines()
print(f"Toplam {len(lines)} satir\n")
target = "BIMAS"

for li, line in enumerate(lines):
    toks = line.split()
    if not toks: continue
    isin_idx = None
    fused_ticker = None
    for i, t in enumerate(toks):
        if f._OCR_STOCK_ISIN_RE.match(t):
            isin_idx = i; break
        m = _ISIN_SUBSTR.search(t)
        if m and m.end() >= len(t) - 1:
            cand = fused_extract(t[:m.start()])
            if cand:
                fused_ticker = cand
                isin_idx = i; break
    if isin_idx is None: continue

    ticker = None
    if KNOWN:
        for tk in toks[:isin_idx]:
            tk = tk.strip(":,;()")
            if tk in KNOWN and tk not in f._TICKER_BLACKLIST and tk not in f._OCR_WORD_BLACKLIST:
                ticker = tk; break
    if ticker is None and fused_ticker is not None:
        ticker = fused_ticker
    if ticker is None:
        ticker = first_valid(toks[:isin_idx])
    if ticker is None and li > 0:
        ticker = first_valid(lines[li-1].split())
    if ticker is None and li > 1:
        ticker = first_valid(lines[li-2].split())
    if ticker is None: continue

    if ticker == target:
        print(f"Line {li+1}: {line!r}")
        tail = toks[isin_idx+1:]
        if li+1 < len(lines):
            extra = lines[li+1].split()
            if extra and all(f._OCR_NUMBER_RE.match(x.strip(",.;")) for x in extra):
                tail = tail + extra
                print(f"  extended with line {li+2}: {extra!r}")
        pcts = []
        for t in tail:
            p = f._ocr_to_pct(t)
            if p is not None: pcts.append(p)
        if not pcts and li+1 < len(lines):
            pcts = [p for p in (f._ocr_to_pct(t) for t in lines[li+1].split()) if p is not None]
        if not pcts and li+2 < len(lines):
            pcts = [p for p in (f._ocr_to_pct(t) for t in lines[li+2].split()) if p is not None]
        if not pcts and li > 0:
            pcts = [p for p in (f._ocr_to_pct(t) for t in lines[li-1].split()) if p is not None]
        print(f"  tail: {tail!r}")
        print(f"  pcts: {pcts}")
        print(f"  oran = {pcts[-1] if pcts else 'NONE'}")
        print()
