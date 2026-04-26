"""ADP'nin tum sayfalarinda AKBNK satirlarini bul."""
import re
from pathlib import Path
import pymupdf

doc = pymupdf.open(stream=Path("tools/probe_detail2_out/_ADP.pdf").read_bytes(), filetype="pdf")
print(f"Pages: {len(doc)}")
for pi, page in enumerate(doc):
    words = page.get_text("words")
    bucket = {}
    for w in words:
        yk = int(round(w[1] / 3.0))
        bucket.setdefault(yk, []).append(w)
    for yk in sorted(bucket.keys()):
        line = sorted(bucket[yk], key=lambda t: t[0])
        toks = [t[4] for t in line]
        if len(toks) >= 1 and toks[0] == "AKBNK":
            print(f"  p{pi} y={yk*3}: {toks}")
