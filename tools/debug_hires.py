"""Hires OCR debug."""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import fon_hisse_scraper as f  # noqa: E402
import pymupdf, io
from PIL import Image
import numpy as np

pdf = (ROOT / "data" / "_failed_pdfs" / "NKT.pdf").read_bytes()
doc = pymupdf.open(stream=pdf, filetype="pdf")
print(f"pages: {doc.page_count}")

eng = f._get_rapidocr()
print(f"engine: {bool(eng)}")

for dpi in (220, 300):
    print(f"\n--- DPI {dpi} ---")
    zoom = dpi / 72.0
    mat = pymupdf.Matrix(zoom, zoom)
    parts = []
    for pi, page in enumerate(doc):
        pix = page.get_pixmap(matrix=mat, alpha=False)
        png = pix.tobytes("png")
        try:
            im = Image.open(io.BytesIO(png)).convert("RGB")
            arr = np.array(im)
            print(f"  page {pi}: pixmap {pix.width}x{pix.height} -> arr {arr.shape}")
        except Exception as e:
            print(f"  page {pi}: PIL hata: {e}")
            continue
        try:
            result, _ = eng(arr)
            print(f"  page {pi}: ocr items: {len(result) if result else 0}")
            if result:
                # ilk 3 satir
                for r in result[:3]:
                    print(f"    {r[1]!r} (conf={r[2]:.2f})")
        except Exception as e:
            print(f"  page {pi}: ocr hata: {e}")
            import traceback; traceback.print_exc()
