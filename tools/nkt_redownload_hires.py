"""NKT PDF'i yeniden indir ve hires OCR ile metne cevir."""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import fon_hisse_scraper as f  # noqa: E402

sess = f._session()
# NKT'nin KAP linki (fon_hisse_birlesik.json'dan)
kap_link = "https://www.kap.org.tr/tr/fon-bilgileri/genel/nkt-nurol-portfoy-birinci-katilim-hisse-senedi-fonu-hisse-senedi-yogun-fon"

print(f"kap_link: {kap_link}")
obj_id = f._extract_kap_obj_id(sess, kap_link)
print(f"objId: {obj_id}")
if not obj_id:
    sys.exit(1)

discs = f._fetch_pdr_disclosures(sess, obj_id)
print(f"disclosures: {len(discs)}")
if not discs:
    sys.exit(1)

best = None
for d in discs[:3]:
    di = d.get("disclosure_index")
    atts = f._list_disclosure_attachments(sess, di)
    if not atts:
        continue
    ranked = f._pick_pdr_attachment(atts, kod="NKT")
    print(f"  d={di} dt={d.get('publish_date')} atts={len(atts)} top_label={ranked[0].get('label') if ranked else None}")
    if ranked:
        best = (di, ranked[0], d.get('publish_date'))
        break

if not best:
    print("PDR bulunamadi"); sys.exit(1)

di, pdr, dt = best
file_id = pdr.get("file_id")
print(f"fileId: {file_id} label: {pdr.get('label')} dt: {dt}")
pdf = f._download_kap_pdf(sess, file_id)
if not pdf:
    print("PDF indirilemedi"); sys.exit(1)
out_pdf = ROOT / "data" / "_failed_pdfs" / "NKT.pdf"
out_pdf.parent.mkdir(parents=True, exist_ok=True)
out_pdf.write_bytes(pdf)
print(f"PDF: {out_pdf} ({len(pdf)} bytes)")

# Hires OCR (300 DPI - 350 PIL bombasi olusturuyor; 300 ile yeterli detay)
text = f._pdf_ocr_text(pdf, dpi=300)
out_txt = ROOT / "data" / "_ocr_text" / "NKT_hires.txt"
out_txt.write_text(text, encoding="utf-8")
print(f"hires OCR: {out_txt} ({len(text)} chars)")
