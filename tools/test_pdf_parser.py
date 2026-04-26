"""3 farkli PDF formati ile parser dogrulama."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fon_hisse_scraper import extract_hisse_rows_from_pdr_pdf

CASES = {
    "MAC (yeni .E format)": "tools/probe_detail2_out/MAC.pdf",
    "ADP (eski sade)": "tools/probe_detail2_out/_ADP.pdf",
    "AHI (% onde)": "tools/probe_detail2_out/_AHI.pdf",
    "ICF": "tools/probe_detail2_out/_ICF.pdf",
}

for name, p in CASES.items():
    pdf_bytes = Path(p).read_bytes()
    rows, err = extract_hisse_rows_from_pdr_pdf(pdf_bytes)
    total = sum(r["agirlik"] for r in rows)
    print(f"\n=== {name} ===")
    print(f"  err={err}  rows={len(rows)}  toplam={total:.2f}%")
    for r in rows[:8]:
        print(f"    {r['ticker']:8} {r['agirlik']:>6.2f}%")
    if len(rows) > 8:
        print(f"    ... ve {len(rows) - 8} hisse daha")
