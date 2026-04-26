"""Ziraat (TZD/ZHH/ZJL/ZJV/ZLH/ZPE) PDFlerinin text yapisini incele."""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pymupdf  # noqa: E402

PDFS = ROOT / "data" / "_failed_pdfs"

def show(code: str, max_pages: int = 3, max_chars: int = 5000):
    p = PDFS / f"{code}.pdf"
    doc = pymupdf.open(p)
    print("\n" + "#"*100)
    print(f"# {code}.pdf  (pages={len(doc)})")
    print("#"*100)
    for pi, page in enumerate(doc[:max_pages]):
        text = page.get_text("text")
        print(f"\n----- {code} PAGE {pi+1} (len={len(text)}) -----")
        out = text[:max_chars]
        print(out)
        if len(text) > max_chars:
            print(f"... [+{len(text)-max_chars} chars] ...")


for code in ["ZHH","ZJL","ZJV","ZLH","ZPE","TZD"]:
    show(code, max_pages=4, max_chars=3500)
