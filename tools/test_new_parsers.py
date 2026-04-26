"""Yeni parser denemeleri - Ziraat / satislar formatlari icin sandbox."""
from __future__ import annotations
import re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pymupdf  # noqa: E402

PDFS = ROOT / "data" / "_failed_pdfs"


# ============= ZIRAAT ============= 
# Bolumler: "3 - FON PORTFOY DEGERI TABLOSU" altinda
#   "A - HISSE SENETLERI ..." satirlari => buradan ticker + oran(%)
# Ornek: "                 1 AEFES.E             ANADOLU EFES             214.605,000    3.601.071,90        3,459470               18,862"
# Yapi: NUM TICKER.E IHRACCI NOMINAL RAYIC ORAN BIRIM_ALIS  (son 3-4 numerik)
# Oran (%): 4-6 ondalikli yuzde (3,459470)

ZIRAAT_BLOCK_START = re.compile(
    r"3\s*-\s*FON\s+PORTF[ÖO]Y\s+DE[ĞG]ER[İI]\s+TABLOSU.*?A\s*-\s*H[İI]SSE\s+SENETLER[İI]",
    re.IGNORECASE | re.DOTALL,
)
# 1.HISSE SENETLERI bolumu son: B,C,D ... gibi yeni bolum baslayinca son
ZIRAAT_BLOCK_END = re.compile(
    r"\n\s*B\s*-\s*DEVLET\s+TAHV[İI]L[İI]|\n\s*B\s*-\s*[A-Z][A-ZÇĞİÖŞÜ]{4,}",
    re.IGNORECASE,
)
# Satir: numara (1+) + TICKER.E + ... + 3-4 sayi
ZIRAAT_ROW_RE = re.compile(
    r"^\s*\d{1,3}\s+([A-Z0-9]{2,6})\.E\s+.+?\s+"  # numara, ticker, ihracci
    r"([\d.]+,\d{1,3})\s+"      # nominal
    r"([\d.]+,\d{1,4})\s+"      # rayic deger
    r"(-?\d{1,3},\d{1,6})\s+"   # oran %  <-- bu istenen
    r"([\d.]+,\d{1,4})\s*$",    # birim alis
    re.MULTILINE,
)


def parse_ziraat(text: str) -> list[tuple[str, float]]:
    """Ziraat AYLIK RAPOR -> [(ticker, oran%)] listesi."""
    m = ZIRAAT_BLOCK_START.search(text)
    if not m:
        return []
    sub = text[m.end():]
    me = ZIRAAT_BLOCK_END.search(sub)
    if me:
        sub = sub[:me.start()]
    rows: list[tuple[str, float]] = []
    for r in ZIRAAT_ROW_RE.finditer(sub):
        ticker = r.group(1)
        oran_str = r.group(4).replace(",", ".")
        try:
            oran = float(oran_str)
        except ValueError:
            continue
        if 0 < oran <= 50:
            rows.append((ticker, oran))
    return rows


def is_ziraat_template(text: str) -> bool:
    return bool(re.search(r"AYLIK\s+RAPOR.*FONU\s+TANITICI", text, re.DOTALL))


def main():
    for code in ["ZHH", "ZJL", "ZJV", "ZLH", "ZPE", "TZD"]:
        p = PDFS / f"{code}.pdf"
        if not p.is_file():
            print(f"{code}: pdf yok"); continue
        doc = pymupdf.open(p)
        full = "".join(page.get_text("text") + "\n" for page in doc)
        ziraat = is_ziraat_template(full)
        rows = parse_ziraat(full) if ziraat else []
        # Aggregate dups
        agg: dict[str, float] = {}
        for t, o in rows:
            agg[t] = agg.get(t, 0.0) + o
        total = sum(agg.values())
        print(f"\n{code}: ziraat={ziraat}  satir={len(rows)}  unique_ticker={len(agg)}  toplam_oran={total:.2f}%")
        for t, o in sorted(agg.items(), key=lambda x: -x[1])[:8]:
            print(f"   {t:8} {o:8.4f}%")


if __name__ == "__main__":
    main()
