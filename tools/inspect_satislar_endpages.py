"""DHJ/IIH/IMB/IVF son sayfalarini incele."""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pymupdf  # noqa: E402

PDFS = ROOT / "data" / "_failed_pdfs"

for code in ["DHJ", "IMB", "IIH", "IVF"]:
    p = PDFS / f"{code}.pdf"
    doc = pymupdf.open(p)
    print(f"\n{'#'*80}\n# {code}.pdf  ({len(doc)} pages, size={p.stat().st_size})\n{'#'*80}")
    n = len(doc)
    # son 3 sayfa
    for pi in range(max(0, n-3), n):
        text = doc[pi].get_text("text")
        print(f"\n----- {code} PAGE {pi+1} (len={len(text)}) -----")
        print(text[:5000])
        if len(text) > 5000:
            print(f"... [+{len(text)-5000} chars]")
