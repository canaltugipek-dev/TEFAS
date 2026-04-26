"""DHJ/IIH/IMB/IVF/HBU icin DOGRU eki indir ve parse edebiliyor muyuz bak."""
from __future__ import annotations
import sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pymupdf  # noqa: E402
from fon_hisse_scraper import _session, _download_kap_pdf, extract_hisse_rows_from_pdr_pdf  # noqa: E402

# Disclosure attachment debug'dan alinan dogru file_id'ler (suffix'siz)
TARGETS = {
    "DHJ":  "4028328d9d4a0485019d530a44565c50",  # DHJ_2026.03.pdf
    "IMB":  "4028328c9d4a029c019d62d360b01a8a",  # IMB_2026.03.pdf
    "IIH":  "4028328c9d4a029c019d62d35fcf1a74",  # IIH_2026.03.pdf
    "IVF":  "4028328c9d4a029c019d62d3641f1acc",  # IVF_2026.03.pdf
    "HBU":  "4028328d9d4a0485019d6c13673170e5",  # HBU_2026.03.pdf
}

OUT = ROOT / "data" / "_correct_pdrs"
OUT.mkdir(parents=True, exist_ok=True)

sess = _session()
for code, fid in TARGETS.items():
    pdf_path = OUT / f"{code}_correct.pdf"
    if not pdf_path.is_file():
        time.sleep(4)
        print(f"[{code}] indiriliyor (file_id={fid})...")
        pdf = _download_kap_pdf(sess, fid)
        if not pdf:
            print(f"  [{code}] indirilemedi"); continue
        pdf_path.write_bytes(pdf)
        print(f"  -> {pdf_path}  ({len(pdf)} bytes)")
    else:
        pdf = pdf_path.read_bytes()
        print(f"[{code}] zaten var ({pdf_path.stat().st_size} bytes)")

    # Bilgi
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    text = "".join(p.get_text("text") + "\n" for p in doc)
    head = "\n".join(line for line in text.splitlines()[:30])
    print(f"  pages={len(doc)}  text_len={len(text.strip())}")
    print(f"  HEAD:\n    " + head.replace("\n", "\n    ")[:600])
    rows, err = extract_hisse_rows_from_pdr_pdf(pdf)
    print(f"  extract_hisse: rows={len(rows)} err={err!r}")
    if rows:
        for r in rows[:5]:
            print(f"    {r['ticker']:8} {r['agirlik']:.4f}%")
    print()
