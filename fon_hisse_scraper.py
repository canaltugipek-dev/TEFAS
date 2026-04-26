#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fon Hisse Detay — KAP Portföy Dağılım Raporu (PDR) PDF'inden gerçek hisse ağırlıkları.

Akış:
  1) TEFAS GetAllFundAnalyzeData → KAP linki + varlık dağılımı (hisse yoğunluk kontrolü).
  2) KAP API: PDR bildirimleri listelenir, en güncel tarih seçilir.
  3) Bildirim sayfasından PDF file id → indirme URL'si.
  4) PyMuPDF: satır bazlı kelime hizası ile Hisse Kodu + son sütun % oranı okunur.
  5) data/fon_hisse_birlesik.json + fon başına data/<KOD>_hisse_pdr.json güncellenir.

Uydurma veri üretilmez; tablo okunamazsa hisse_mesaj = "Veri okunamadı".
İstekler arası bekleme: --delay (varsayılan 2.0 sn, KAP yükünü azaltmak için).

Kurulum: py -m venv .venv  →  .venv/Scripts/python -m pip install -r requirements.txt
"""

from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pymupdf
import requests
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT_PATH = DATA / "fon_hisse_birlesik.json"
MANIFEST_PATH = DATA / "manifest.json"


def per_fund_hisse_path(kod: str) -> Path:
    """Fon bazlı hisse PDR çıktısı (AAV_tefas.json fiyat dosyasına dokunmaz)."""
    return DATA / f"{kod.strip().upper()}_hisse_pdr.json"

TEFAS_ANALYZE = "https://www.tefas.gov.tr/api/DB/GetAllFundAnalyzeData"
KAP_DISCLOSURE_FILTER_URL = "https://kap.org.tr/tr/api/disclosure/filter/FILTERYFBF"
KAP_DISCLOSURE_PAGE_URL = "https://kap.org.tr/tr/Bildirim"
KAP_FILE_DOWNLOAD_URL = "https://kap.org.tr/tr/api/file/download"
KAP_PORTFOY_DISCLOSURE_TYPE = "8aca490d502e34b801502e380044002b"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": "https://www.tefas.gov.tr",
    "Referer": "https://www.tefas.gov.tr/FonAnaliz.aspx",
}

# PDR tablosunda hisse kodu dışı görünen kısaltmalar (yanlış pozitif)
_TICKER_BLACKLIST = frozenset(
    {
        "SWAP",
        "GOS",
        "GES",
        "TOPLAM",
        "FON",
        "TRY",
        "TL",
        "PDF",
        "BORC",
        "BOR",
        "TABLO",
    }
)


class _LegacySSLAdapter(HTTPAdapter):
    def __init__(self, ssl_context=None, **kwargs):
        self._ssl_context = ssl_context
        super().__init__(**kwargs)

    def init_poolmanager(self, connections, maxsize, block=False):
        self.poolmanager = PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            ssl_context=self._ssl_context,
        )


def _session() -> requests.Session:
    s = requests.Session()
    try:
        ctx = ssl.create_default_context()
        ctx.options |= 0x4
        s.mount("https://", _LegacySSLAdapter(ctx))
    except Exception:
        pass
    return s


def _load_manifest_codes() -> List[str]:
    if not MANIFEST_PATH.is_file():
        return []
    try:
        with MANIFEST_PATH.open(encoding="utf-8") as f:
            m = json.load(f)
        return [str(x["kod"]).strip().upper() for x in m.get("fonlar", []) if x.get("kod")]
    except (json.JSONDecodeError, OSError, KeyError):
        return []


def fetch_tefas_analyze(sess: requests.Session, kod: str) -> Optional[Dict[str, Any]]:
    kod = kod.strip().upper()
    try:
        r = sess.post(
            TEFAS_ANALYZE,
            data={"dil": "TR", "fonkod": kod},
            headers=HEADERS,
            timeout=45,
        )
        if not r.ok:
            return None
        t = r.text.strip()
        if not t.startswith("{"):
            return None
        return r.json()
    except Exception:
        return None


def _extract_kap_obj_id(sess: requests.Session, kap_link: Optional[str]) -> Optional[str]:
    if not kap_link:
        return None
    try:
        r = sess.get(kap_link, timeout=45, headers=HEADERS)
        if not r.ok:
            return None
        m = re.search(r"objId[\\\"':]+([A-Fa-f0-9]{32})", r.text)
        return m.group(1).upper() if m else None
    except Exception:
        return None


def _parse_publish_date(s: Optional[str]) -> datetime:
    """KAP publishDate: '07.04.2026 12:01:59' veya sadece tarih."""
    if not s or not str(s).strip():
        return datetime.min
    part = str(s).strip().split()[0]
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(part, fmt)
        except ValueError:
            continue
    return datetime.min


def _fetch_pdr_disclosures(sess: requests.Session, kap_obj_id: str) -> List[Dict[str, Any]]:
    url = f"{KAP_DISCLOSURE_FILTER_URL}/{kap_obj_id}/{KAP_PORTFOY_DISCLOSURE_TYPE}/365"
    try:
        r = sess.get(url, timeout=45, headers=HEADERS)
        if not r.ok:
            return []
        arr = r.json()
        if not isinstance(arr, list):
            return []
        out: List[Dict[str, Any]] = []
        for item in arr:
            basic = (item or {}).get("disclosureBasic") or {}
            if not basic.get("disclosureIndex"):
                continue
            out.append(
                {
                    "disclosure_id": basic.get("disclosureId"),
                    "disclosure_index": basic.get("disclosureIndex"),
                    "publish_date": basic.get("publishDate"),
                    "title": basic.get("title"),
                    "year": basic.get("year"),
                    "period": basic.get("donem"),
                }
            )
        out.sort(key=lambda d: _parse_publish_date(d.get("publish_date")), reverse=True)
        return out
    except Exception:
        return []


def _fetch_file_id_from_disclosure_page(sess: requests.Session, disclosure_index: Any) -> Optional[str]:
    if not disclosure_index:
        return None
    try:
        r = sess.get(f"{KAP_DISCLOSURE_PAGE_URL}/{disclosure_index}", timeout=45, headers=HEADERS)
        if not r.ok:
            return None
        m = re.search(r"file/download/([a-f0-9]{32})", r.text)
        return m.group(1) if m else None
    except Exception:
        return None


def _download_kap_pdf(sess: requests.Session, file_id: str) -> Optional[bytes]:
    try:
        r = sess.get(f"{KAP_FILE_DOWNLOAD_URL}/{file_id}", timeout=60, headers=HEADERS)
        if not r.ok:
            return None
        data = r.content
        i = data.find(b"%PDF-")
        return data[i:] if i >= 0 else None
    except Exception:
        return None


def _pdf_download_url(file_id: str) -> str:
    return f"{KAP_FILE_DOWNLOAD_URL}/{file_id}"


def _pdf_has_hisse_section(pdf_bytes: bytes) -> bool:
    """PORTFÖY YAPISI / HİSSE SENETLERİ bölümü için kaba kontrol."""
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return False
    full = ""
    for page in doc:
        full += page.get_text("text") + "\n"
    u = full.upper()
    if "HISSE" in u and "SENET" in u:
        return True
    if "PORTF" in u and "YAP" in u:
        return True
    return False


def extract_hisse_rows_from_pdr_pdf(pdf_bytes: bytes) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    AAV ile doğrulanmış PDR tablo ayıklama: PyMuPDF kelime satırları, ilk token hisse kodu,
    son token 'xx,xx%' (Toplam portföy içindeki oran).

    Tüm fonlar için aynı mantık; uydurma veri üretilmez.
    """
    pct_re = re.compile(r"^-?\d{1,3}[.,]\d{2}%$")
    # BIST: çoğunlukla 4–5 harf; 3 harf satırlar (GOS vb.) ve yönetici satırları (AAL…) elenir.
    tick_re = re.compile(r"^[A-Z]{4,6}$")

    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        return [], f"PDF açılamadı: {e}"

    if not _pdf_has_hisse_section(pdf_bytes):
        return [], "Veri okunamadı"

    raw: List[Tuple[str, float, int]] = []

    for pi, page in enumerate(doc):
        words = page.get_text("words")
        if not words:
            continue
        by_y: Dict[float, List[Any]] = {}
        for w in words:
            y = round(w[1], 0)
            by_y.setdefault(y, []).append(w)
        for y in sorted(by_y.keys()):
            line_words = sorted(by_y[y], key=lambda t: t[0])
            tokens = [t[4].strip() for t in line_words if t[4].strip()]
            if len(tokens) < 2:
                continue
            first, last = tokens[0], tokens[-1]
            if first in _TICKER_BLACKLIST:
                continue
            if not tick_re.match(first):
                continue
            if not pct_re.match(last):
                continue
            try:
                p = float(last.replace(",", ".").replace("%", ""))
            except ValueError:
                continue
            if p <= 0 or p > 30:
                continue
            raw.append((first, p, pi))

    if not raw:
        return [], "Veri okunamadı"

    # Aynı kod birden fazla satırda görünürse en yüksek oranı tut
    best: Dict[str, Dict[str, Any]] = {}
    for ticker, pct, _ in raw:
        cur = best.get(ticker)
        if cur is None or pct > cur["agirlik"]:
            best[ticker] = {"ticker": ticker, "ad": "", "agirlik": round(pct, 4)}

    out = sorted(best.values(), key=lambda r: -r["agirlik"])
    return out, None


def apply_pdr_pdf_extraction(pdf_bytes: bytes) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """PDF baytlarından hisse listesini çıkarır (`extract_hisse_rows_from_pdr_pdf` ile aynı)."""
    return extract_hisse_rows_from_pdr_pdf(pdf_bytes)


def fetch_real_hisse_rows(
    sess: requests.Session,
    kod: str,
    tefas_payload: Optional[Dict[str, Any]],
    log: bool = True,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "hisseler": [],
        "hisse_durumu": "bulunamadi",
        "hisse_mesaj": "Veri okunamadı",
        "kap_rapor_tarihi": None,
        "kap_pdf_url": None,
    }
    if not tefas_payload:
        out["hisse_mesaj"] = "TEFAS verisi alınamadı."
        return out

    fp = (tefas_payload.get("fundProfile") or [{}])[0]
    kap_link = fp.get("KAPLINK")
    alloc = tefas_payload.get("fundAllocation") or []
    hisse_pct: Optional[float] = None
    for row in alloc:
        tip = str(row.get("KIYMETTIP") or "").strip().lower()
        if "hisse" in tip:
            try:
                hisse_pct = float(row.get("PORTFOYORANI") or 0.0)
            except (TypeError, ValueError):
                hisse_pct = 0.0
            break

    if hisse_pct is not None and hisse_pct < 10:
        out["hisse_durumu"] = "uygun_degil"
        out["hisse_mesaj"] = "Bu fon hisse senedi yoğun bir fon değildir."
        return out

    kap_obj_id = _extract_kap_obj_id(sess, kap_link)
    if not kap_obj_id:
        out["hisse_mesaj"] = "KAP fon kimliği bulunamadı."
        return out

    disclosures = _fetch_pdr_disclosures(sess, kap_obj_id)
    if not disclosures:
        out["hisse_mesaj"] = "KAP portföy dağılım raporu bulunamadı."
        return out

    disclosure = disclosures[0]
    out["kap_rapor_tarihi"] = disclosure.get("publish_date")

    file_id = _fetch_file_id_from_disclosure_page(sess, disclosure.get("disclosure_index"))
    if not file_id:
        out["hisse_mesaj"] = "KAP rapor eki bulunamadı."
        return out

    pdf_url = _pdf_download_url(file_id)
    out["kap_pdf_url"] = pdf_url

    if log:
        print(
            f"[KAP] {kod}: PDR indiriliyor — tarih: {disclosure.get('publish_date')!r}, URL: {pdf_url}",
            flush=True,
        )

    pdf = _download_kap_pdf(sess, file_id)
    if not pdf:
        out["hisse_mesaj"] = "KAP rapor PDF indirilemedi."
        return out

    rows, err = apply_pdr_pdf_extraction(pdf)
    if err or not rows:
        out["hisse_mesaj"] = err or "Veri okunamadı"
        if log:
            print(f"[KAP] {kod}: hisse satırı okunamadı ({out['hisse_mesaj']})", flush=True)
        return out

    out["hisseler"] = rows
    out["hisse_durumu"] = "ok"
    out["hisse_mesaj"] = f"{len(rows)} hisse satırı okundu."
    if log:
        print(f"[KAP] {kod}: {len(rows)} adet hisse bulundu (PDR).", flush=True)

    return out


def merge_one(
    kod: str,
    tefas: Optional[Dict[str, Any]],
    hisse_result: Dict[str, Any],
) -> Dict[str, Any]:
    kod = kod.strip().upper()
    block: Dict[str, Any] = {
        "kod": kod,
        "guncelleme": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "kaynak_tefas": tefas is not None,
        "unvan": None,
        "kap_link": None,
        "varlik_dagilimi": [],
        "hisseler": list(hisse_result.get("hisseler") or []),
        "hisse_durumu": hisse_result.get("hisse_durumu") or "bulunamadi",
        "hisse_mesaj": hisse_result.get("hisse_mesaj") or "",
        "kap_rapor_tarihi": hisse_result.get("kap_rapor_tarihi"),
    }
    if hisse_result.get("kap_pdf_url"):
        block["kap_pdf_url"] = hisse_result["kap_pdf_url"]

    if tefas:
        fi = (tefas.get("fundInfo") or [{}])[0]
        fp = (tefas.get("fundProfile") or [{}])[0]
        block["unvan"] = fi.get("FONUNVAN") or fp.get("FONUNVAN")
        block["kap_link"] = fp.get("KAPLINK")
        alloc = tefas.get("fundAllocation") or []
        for row in alloc:
            tip = (row.get("KIYMETTIP") or "").strip()
            try:
                oran = float(row.get("PORTFOYORANI") or 0)
            except (TypeError, ValueError):
                oran = 0.0
            if tip:
                block["varlik_dagilimi"].append({"tip": tip, "oran": round(oran, 4)})

    return block


def _write_per_fund_json(kod: str, block: Dict[str, Any]) -> None:
    path = per_fund_hisse_path(kod)
    with path.open("w", encoding="utf-8") as f:
        json.dump(block, f, ensure_ascii=False, indent=2)


def _ozet_satir(kod: str, block: Dict[str, Any]) -> Dict[str, Any]:
    durum = block.get("hisse_durumu") or "bulunamadi"
    n = len(block.get("hisseler") or [])
    msg = (block.get("hisse_mesaj") or "")[:70]
    if durum == "ok":
        etiket = "OK"
    elif durum == "uygun_degil":
        etiket = "Uygun değil"
    else:
        etiket = "Hata"
    return {"kod": kod, "etiket": etiket, "durum": durum, "hisse_adet": n, "mesaj": msg}


def _print_ozet_tablo(satirlar: List[Dict[str, Any]]) -> None:
    print("", flush=True)
    print("=" * 88, flush=True)
    print("ÖZET — KAP PDR hisse çekimi", flush=True)
    print("=" * 88, flush=True)
    ok_n = sum(1 for s in satirlar if s["durum"] == "ok")
    uy_n = sum(1 for s in satirlar if s["durum"] == "uygun_degil")
    err_n = sum(1 for s in satirlar if s["durum"] not in ("ok", "uygun_degil"))
    print(f"  Başarılı (hisse listesi): {ok_n}  |  Hisse yoğun değil: {uy_n}  |  Hata / veri yok: {err_n}", flush=True)
    print("-" * 88, flush=True)
    col_kod, col_et, col_n, col_msg = 6, 14, 7, 48
    hdr = f"{'Kod':<{col_kod}} {'Durum':<{col_et}} {'#Hisse':>{col_n}}  {'Mesaj':<{col_msg}}"
    print(hdr, flush=True)
    print("-" * 88, flush=True)
    for s in satirlar:
        line = f"{s['kod']:<{col_kod}} {s['etiket']:<{col_et}} {s['hisse_adet']:>{col_n}}  {s['mesaj']:<{col_msg}}"
        print(line, flush=True)
    print("=" * 88, flush=True)


def run(codes: List[str], delay_s: float = 2.0) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    sess = _session()
    birlesik: Dict[str, Any] = {
        "aciklama": (
            "TEFAS meta + KAP Portföy Dağılım Raporu PDF'inden okunan gerçek hisse ağırlıkları."
        ),
        "guncelleme": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fonlar": {},
    }
    ozet: List[Dict[str, Any]] = []

    for i, kod in enumerate(codes):
        kod = kod.strip().upper()
        if not kod:
            continue
        if i and delay_s:
            time.sleep(delay_s)
        tefas = fetch_tefas_analyze(sess, kod)
        hisse_result = fetch_real_hisse_rows(sess, kod, tefas, log=True)
        block = merge_one(kod, tefas, hisse_result)
        birlesik["fonlar"][kod] = block
        _write_per_fund_json(kod, block)
        ozet.append(_ozet_satir(kod, block))

    return birlesik, ozet


def main() -> int:
    ap = argparse.ArgumentParser(description="KAP PDR PDF → gerçek hisse ağırlıkları → JSON")
    ap.add_argument("fonlar", nargs="*", help="Fon kodları (örn: AAV ACC)")
    ap.add_argument(
        "--tum-manifest",
        action="store_true",
        help="manifest.json'daki tüm fon kodlarını işle",
    )
    ap.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Fonlar arası bekleme saniye (varsayılan 2, KAP için önerilir)",
    )
    args = ap.parse_args()

    if args.tum_manifest:
        codes = _load_manifest_codes()
        if not codes:
            print("manifest.json bulunamadı veya fon yok.", file=sys.stderr)
            return 1
    else:
        codes = [c.upper() for c in args.fonlar if c.strip()]
        if not codes:
            print("Örnek: py fon_hisse_scraper.py AAV ACC", file=sys.stderr)
            print("       py fon_hisse_scraper.py --tum-manifest", file=sys.stderr)
            return 1

    DATA.mkdir(parents=True, exist_ok=True)
    birlesik, ozet = run(codes, delay_s=args.delay)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(birlesik, f, ensure_ascii=False, indent=2)
    print(f"Yazıldı: {OUT_PATH} ({len(birlesik['fonlar'])} fon)", flush=True)
    print(f"Fon başı dosya: {DATA / '<KOD>_hisse_pdr.json'}", flush=True)
    _print_ozet_tablo(ozet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
