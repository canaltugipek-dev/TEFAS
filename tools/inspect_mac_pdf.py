"""MAC PDR PDF'ini indir ve sayfa metnini, kelime tablosunu yazdir."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymupdf
import requests

URL = "https://kap.org.tr/tr/api/file/download/4028328c9d4a029c019d6d47a555541f"
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

r = requests.get(URL, headers=UA, timeout=60)
data = r.content
i = data.find(b"%PDF-")
pdf = data[i:] if i >= 0 else None
if not pdf:
    print("No PDF marker")
    sys.exit(1)

Path("tools/probe_detail2_out/MAC.pdf").write_bytes(pdf)
print(f"Saved PDF, len={len(pdf)} bytes")

doc = pymupdf.open(stream=pdf, filetype="pdf")
print(f"Pages: {len(doc)}")
for pi, page in enumerate(doc):
    print(f"\n=== Page {pi} ===")
    text = page.get_text("text")
    print(text[:4000])
    print("..." if len(text) > 4000 else "")
