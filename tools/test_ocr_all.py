"""5 image-only PDF'i ISIN-bazli OCR parser ile test et."""
from __future__ import annotations
import sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fon_hisse_scraper import extract_hisse_rows_from_pdr_pdf  # noqa: E402

PDFS = ROOT / "data" / "_failed_pdfs"

for code in ["DTH", "NKT", "NLE", "NPH", "SUR"]:
    p = PDFS / f"{code}.pdf"
    if not p.is_file():
        print(f"!! {code} pdf yok"); continue
    pdf = p.read_bytes()
    t0 = time.time()
    rows, err = extract_hisse_rows_from_pdr_pdf(pdf)
    elapsed = time.time() - t0
    total = sum(r["agirlik"] for r in rows)
    print(f"\n{code:5}  {elapsed:5.1f}s  rows={len(rows):>3}  toplam={total:6.2f}%  err={err!r}")
    for r in rows[:8]:
        print(f"   {r['ticker']:8} {r['agirlik']:7.4f}%")
