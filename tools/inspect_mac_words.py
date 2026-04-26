"""MAC PDF'inde kelime tablosunu y koordinatina gore satira ayir, ticker satirlarini bul."""
from pathlib import Path
import pymupdf

doc = pymupdf.open(stream=Path("tools/probe_detail2_out/MAC.pdf").read_bytes(), filetype="pdf")
print(f"pages={len(doc)}")
for pi, page in enumerate(doc):
    print(f"\n=== Page {pi} ===")
    words = page.get_text("words")
    by_y = {}
    for w in words:
        y = round(w[1], 0)
        by_y.setdefault(y, []).append(w)
    for y in sorted(by_y.keys())[:80]:
        line = sorted(by_y[y], key=lambda t: t[0])
        toks = [t[4] for t in line]
        print(f"  y={y:>6}: {toks}")
