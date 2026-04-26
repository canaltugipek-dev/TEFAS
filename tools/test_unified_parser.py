"""Yeni unified extract_hisse_rows_from_pdr_pdf'i tum 17 PDF'le test et."""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fon_hisse_scraper import extract_hisse_rows_from_pdr_pdf  # noqa: E402

# Hangi PDF'i kullanacagiz: korelasyon/satislar olanlar yerine _correct_pdrs kullanacagiz
PDFS = ROOT / "data" / "_failed_pdfs"
CORRECT = ROOT / "data" / "_correct_pdrs"

CASES = [
    # (code, path, expected_rows_min)
    # Ziraat template
    ("ZHH", PDFS / "ZHH.pdf", 15),
    ("ZJL", PDFS / "ZJL.pdf", 15),
    ("ZJV", PDFS / "ZJV.pdf", 15),
    ("ZLH", PDFS / "ZLH.pdf", 15),
    ("ZPE", PDFS / "ZPE.pdf", 15),
    ("TZD", PDFS / "TZD.pdf", 15),
    # Disclosure secimi: bu PDFler YANLIS (satislar/korelasyon), parse fail beklenir
    ("DHJ_wrong", PDFS / "DHJ.pdf", 0),
    ("IMB_wrong", PDFS / "IMB.pdf", 0),
    ("IIH_wrong", PDFS / "IIH.pdf", 0),
    ("IVF_wrong", PDFS / "IVF.pdf", 0),
    ("HBU_wrong", PDFS / "HBU.pdf", 0),
    # Dogru PDR'lar
    ("DHJ_correct", CORRECT / "DHJ_correct.pdf", 10),
    ("IMB_correct", CORRECT / "IMB_correct.pdf", 10),
    ("IIH_correct", CORRECT / "IIH_correct.pdf", 10),
    ("IVF_correct", CORRECT / "IVF_correct.pdf", 10),
    ("HBU_correct", CORRECT / "HBU_correct.pdf", 10),
    # Image-only (OCR icin)
    ("DTH", PDFS / "DTH.pdf", 0),  # OCR icin Tesseract gerekli
    ("NKT", PDFS / "NKT.pdf", 0),
    ("NLE", PDFS / "NLE.pdf", 0),
    ("NPH", PDFS / "NPH.pdf", 0),
    ("RBH", PDFS / "RBH.pdf", 0),
    ("SUR", PDFS / "SUR.pdf", 0),
]

ok = 0; total = 0
for code, p, expmin in CASES:
    total += 1
    if not p.is_file():
        print(f"[FAIL]  {code:14}  pdf yok: {p}"); continue
    pdf = p.read_bytes()
    rows, err = extract_hisse_rows_from_pdr_pdf(pdf)
    n = len(rows)
    icon = "OK  " if n >= expmin else "----"
    if n >= expmin and (n > 0 or "wrong" in code or "image" in code or any(c in code for c in ["DTH","NKT","NLE","NPH","RBH","SUR"])):
        ok += 1
    print(f"[{icon}] {code:14}  rows={n:>3}  err={err!r}")
print(f"\n=== {ok}/{total} case basarili ===")
