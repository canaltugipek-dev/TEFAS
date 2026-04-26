"""NKT PDF'in OZET satirlarini bul: 'TOPLAM' / 'PAY' / 'GENEL' anahtar kelimeler."""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

for src in ["NKT.txt", "NKT_hires.txt"]:
    p = ROOT / "data" / "_ocr_text" / src
    if not p.exists():
        continue
    print(f"\n=== {src} ===")
    text = p.read_text(encoding="utf-8")
    for li, line in enumerate(text.splitlines()):
        u = line.upper()
        if any(k in u for k in ("TOPLAM", "GENEL", "PAY ", "HISSE", "ENERJI ALETLER")):
            print(f"  L{li+1:>3}: {line}")
