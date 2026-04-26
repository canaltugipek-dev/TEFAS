"""Indirilmis PDF'lerin text yapisini detayli incele."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402

PDFS = ROOT / "data" / "_failed_pdfs"


def show(code: str, max_chars: int = 6000):
    p = PDFS / f"{code}.pdf"
    if not p.is_file():
        print(f"!! {code}.pdf yok"); return
    doc = pymupdf.open(p)
    print("\n" + "#"*100)
    print(f"# {code}.pdf  (pages={len(doc)}, size={p.stat().st_size})")
    print("#"*100)
    for pi, page in enumerate(doc[:3]):
        text = page.get_text("text")
        print(f"\n----- {code} PAGE {pi+1} (text len={len(text)}) -----")
        print(text[:max_chars])
        if len(text) > max_chars:
            print(f"\n... [{len(text)-max_chars} more chars truncated] ...")


for code in ["DHJ", "IMB", "IIH", "IVF", "HBU"]:
    show(code, max_chars=4000)
