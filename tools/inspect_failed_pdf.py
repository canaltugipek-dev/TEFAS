"""ADP PDF'ini indir, ilk sayfa metnini, kelime tablosunu yazdir."""
import sys
from pathlib import Path

import pymupdf
import requests

# ADP'nin KAP file id'si log'dan
URLS = {
    "ADP": "https://kap.org.tr/tr/api/file/download/4028328c9d4a029c019d5e2a5d016d02",
    "AHI": "https://kap.org.tr/tr/api/file/download/4028328c9d4a029c019d61f37ec81fb8",
    "ICF": "https://kap.org.tr/tr/api/file/download/4028328d9cc9d32c019d49f55c1547d1",
}
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

for kod, url in URLS.items():
    print(f"\n========== {kod} ==========")
    r = requests.get(url, headers=UA, timeout=60)
    data = r.content
    i = data.find(b"%PDF-")
    pdf = data[i:] if i >= 0 else None
    if not pdf:
        print(f"  No PDF marker, len={len(data)}")
        continue
    Path(f"tools/probe_detail2_out/_{kod}.pdf").write_bytes(pdf)
    print(f"  PDF len={len(pdf)}")
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    print(f"  Pages: {len(doc)}")
    for pi, page in enumerate(doc):
        words = page.get_text("words")
        by_y = {}
        for w in words:
            y = round(w[1], 0)
            by_y.setdefault(y, []).append(w)
        ys = sorted(by_y.keys())
        # Print first 30 lines
        print(f"\n  -- page {pi} (lines={len(ys)}) --")
        for y in ys[:30]:
            line = sorted(by_y[y], key=lambda t: t[0])
            toks = [t[4] for t in line]
            print(f"    y={y:>6}: {toks}")
        if len(ys) > 30:
            print("    ...")
        if pi >= 1:
            break
