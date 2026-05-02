#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fon Hisse Detay — KAP Portföy Dağılım Raporu (PDR) PDF'inden gerçek hisse ağırlıkları.

Akış (Nisan 2026 yeni TEFAS API'sine uyarlandı):
  1) TEFAS yeni Next.js UI: /tr/fon-detayli-analiz/<KOD> sayfasının HTML'inden
     KAP linki + fon kategorisi/unvanı parse edilir (RSC payload).
  2) KAP fon bilgi sayfası -> objId (mkkMemberOidId).
  3) KAP API'leri (kap.org.tr/tr/api/disclosure/filter, file/download) ile en
     güncel "Portföy Dağılım Raporu" bildirimi ve PDF dosyası indirilir.
  4) PyMuPDF: satır bazlı kelime hizası ile Hisse Kodu + son sütun % oranı okunur.
  5) data/fon_hisse_birlesik.json + fon başına data/<KOD>_hisse_pdr.json güncellenir.

İsteğe bağlı incremental: --tum-manifest --sadece-yeni-pdr → önce her fon için KAP bildirim
tarihi (HTTP) ile kayıttaki kap_rapor_tarihi karşılaştırılır; yeni PDR yoksa tarayıcı/PDF yenilenmez.

Uydurma veri üretilmez; tablo okunamazsa hisse_mesaj = "Veri okunamadı".
İstekler arası bekleme: --delay (varsayılan 2.0 sn, KAP yükünü azaltmak için).

Kurulum:
  py -m venv .venv
  .venv/Scripts/python -m pip install -r requirements.txt
  .venv/Scripts/python -m playwright install chromium
"""

from __future__ import annotations

import argparse
import copy
import json
import os
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

from tefas_browser_client import (
    TefasBrowserClient,
    close_browser_client,
    get_browser_client,
)

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT_PATH = DATA / "fon_hisse_birlesik.json"
MANIFEST_PATH = DATA / "manifest.json"


def per_fund_hisse_path(kod: str) -> Path:
    """Fon bazlı hisse PDR çıktısı (AAV_tefas.json fiyat dosyasına dokunmaz)."""
    return DATA / f"{kod.strip().upper()}_hisse_pdr.json"

KAP_DISCLOSURE_FILTER_URL = "https://kap.org.tr/tr/api/disclosure/filter/FILTERYFBF"
KAP_DISCLOSURE_PAGE_URL = "https://kap.org.tr/tr/Bildirim"
KAP_FILE_DOWNLOAD_URL = "https://kap.org.tr/tr/api/file/download"
KAP_PORTFOY_DISCLOSURE_TYPE = "8aca490d502e34b801502e380044002b"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*; q=0.01",
    "Accept-Language": "tr-TR,tr;q=0.9",
}


def _kap_request(
    sess: requests.Session,
    url: str,
    *,
    timeout: int = 45,
    tries: int = 4,
    base_delay: float = 0.8,
) -> Optional[requests.Response]:
    """KAP requests with exponential backoff. None if all attempts fail.

    KAP rate-limits aggressive scraping; on 429/503 (or transient errors), wait and retry.
    """
    last: Optional[requests.Response] = None
    for i in range(tries):
        try:
            r = sess.get(url, timeout=timeout, headers=HEADERS)
            last = r
            if r.ok:
                return r
            if r.status_code in (429, 502, 503, 504):
                time.sleep(base_delay * (2**i))
                continue
            return r
        except requests.RequestException:
            time.sleep(base_delay * (2**i))
            continue
    return last

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
        "PAY",
        "EUR",
        "USD",
        "ALTIN",
    }
)

# Yeni format (2025+) ticker: 2-6 alfanumerik + ".E" (örn AGESA.E, MGROS.E, A1CAP.E)
_TICKER_RE_NEW = re.compile(r"^[A-Z0-9]{2,6}\.E$")
# Eski format (≤2024 PDR'leri): 4-6 büyük harf
_TICKER_RE_OLD = re.compile(r"^[A-Z]{4,6}$")
# Yüzde formatları: "12,34%", "%12,34", "12.34%", "-1,23%"
_PCT_WITH_SYMBOL_RE = re.compile(
    r"^(?:%-?\d{1,3}[.,]\d{1,2}|-?\d{1,3}[.,]\d{1,2}%)$"
)
# % sembolu olmayan numerik tokenlar (sadece ISIN icerigi kanitlanmissa kabul)
_PCT_NO_SYMBOL_RE = re.compile(r"^-?\d{1,3}[.,]\d{1,2}$")
# ISIN: 2 harf prefix + 10 alfanumerik (TR... uluslararasi format)
_ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{10}$")


def _parse_pct(token: str) -> Optional[float]:
    if not token:
        return None
    t = token.strip().replace("%", "").replace(",", ".")
    try:
        v = float(t)
    except ValueError:
        return None
    return v


def _normalize_ticker(token: str) -> Optional[str]:
    """Yeni format AGESA.E -> AGESA; eski format AAYAS -> AAYAS."""
    if _TICKER_RE_NEW.match(token):
        return token.split(".", 1)[0]
    if _TICKER_RE_OLD.match(token):
        return token
    return None


def _looks_like_pct_token(token: str) -> bool:
    return bool(_PCT_WITH_SYMBOL_RE.match(token))


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


def _kategori_ima_eden_hisse_pct(unvan: str, kategori: Optional[str]) -> Optional[float]:
    """Yeni TEFAS UI'da varlık dağılımı yüzdesi yok; kategori/unvana göre
    HSYF olduğunu varsay (>=80%). Aksi halde 0 doner."""
    text = f"{(unvan or '').upper()} | {(kategori or '').upper()}"
    if "HISSE" in text or "HİSSE" in text or "HISSE SENEDI" in text or "HİSSE SENEDİ" in text:
        return 80.0
    return 0.0


def fetch_tefas_analyze(client: TefasBrowserClient, kod: str) -> Optional[Dict[str, Any]]:
    """Yeni TEFAS Next.js detay sayfasından eski analyze JSON'una uyumlu dict üretir.

    Donen yapı (eski yapıyla uyumlu, ek alanlar):
      {
        "fundProfile": [{"FONUNVAN": str, "KAPLINK": str | None}],
        "fundInfo":    [{"FONUNVAN": str}],
        "fundAllocation": [{"KIYMETTIP": "Hisse Senedi", "PORTFOYORANI": float}],
        "fundCategory": str,
        "raw": <browser_client.parse_fund_detail_html dict>
      }
    fundAllocation gerçek değil; kategori/unvana göre türetilmiş bir HSYF işareti.
    """
    kod = kod.strip().upper()
    try:
        info = client.get_fund_kap_info(kod)
    except Exception:
        return None
    if not info:
        return None
    unvan = info.get("fonUnvan") or ""
    kategori = info.get("fonKategori")
    kap_link = info.get("kapLink")
    hisse_pct = _kategori_ima_eden_hisse_pct(unvan, kategori) or 0.0
    payload: Dict[str, Any] = {
        "fundProfile": [
            {
                "FONUNVAN": unvan,
                "KAPLINK": kap_link,
                "RISKDEGERI": info.get("riskDegeri"),
                "ISINKODU": info.get("isinKodu"),
                "TEFASDURUM": info.get("tefasDurum"),
            }
        ],
        "fundInfo": [
            {
                "FONUNVAN": unvan,
                "FIYAT": info.get("sonFiyat"),
                "PORTFOYBUYUKLUGU": info.get("portBuyukluk"),
                "YATIRIMCISAYISI": info.get("yatirimciSayi"),
                "PAZARPAYI": info.get("pazarPayi"),
            }
        ],
        "fundAllocation": [
            {"KIYMETTIP": "Hisse Senedi", "PORTFOYORANI": hisse_pct}
        ],
        "fundCategory": kategori,
        "raw": info,
    }
    return payload


_OBJ_ID_PATTERNS = (
    # /tr/fon-bilgileri/genel/{slug} sayfasinda dogru FUND id'si "objId"
    # alaninda saklanir. mkkMemberOid bazen manager (yonetici sirket) ID'sini
    # gosterir; o nedenle objId ONCE denenir.
    r"\"objId\"\s*:\s*\"([A-Fa-f0-9]{32})\"",
    r"objId\\\"\s*:\s*\\\"([A-Fa-f0-9]{32})\\\"",
    r"objId[\\\"':\s]+([A-Fa-f0-9]{32})",
    # Yedek: bazi sayfalarda (orn. /fon-bildirimleri/{slug}) mkkMemberOid
    # dogrudan fon ID'sidir.
    r"\"mkkMemberOid\"\s*:\s*\"([A-Fa-f0-9]{32})\"",
    r"mkkMemberOid\\\"\s*:\s*\\\"([A-Fa-f0-9]{32})\\\"",
    r"\"oid\"\s*:\s*\"([A-Fa-f0-9]{32})\"",
    r"member-information/([A-Fa-f0-9]{32})",
    r"summary/([A-Fa-f0-9]{32})",
    r"/genel/([A-Fa-f0-9]{32})",
)


def _extract_kap_obj_id(sess: requests.Session, kap_link: Optional[str]) -> Optional[str]:
    if not kap_link:
        return None
    r = _kap_request(sess, kap_link, timeout=45)
    if r is None or not r.ok:
        return None
    text = r.text
    for pat in _OBJ_ID_PATTERNS:
        m = re.search(pat, text)
        if m:
            # KAP API case-sensitive! HTML'deki orijinal case'i koru,
            # eskiden .upper() yapmak 4028... ile baslayan ID'leri bozuyordu.
            return m.group(1)
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
    r = _kap_request(sess, url, timeout=45)
    if r is None or not r.ok:
        return []
    try:
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


def _kap_newest_pdr_publish_raw(sess: requests.Session, kap_link: Optional[str]) -> Optional[str]:
    """KAP filter sonucunun en ustteki bildirimin publishDate (ham string); yok None."""
    if not kap_link or not str(kap_link).strip():
        return None
    oid = _extract_kap_obj_id(sess, str(kap_link).strip())
    if not oid:
        return None
    discs = _fetch_pdr_disclosures(sess, oid)
    if not discs:
        return None
    pd = discs[0].get("publish_date")
    return str(pd).strip() if pd else None


def _pdr_publish_date_cmp(a_raw: Optional[str], b_raw: Optional[str]) -> Optional[int]:
    """Tarihi kiyasla: a > b -> 1; a == b -> 0; a < b -> -1; parse yoksa None."""
    if not a_raw or not str(a_raw).strip():
        return None
    if not b_raw or not str(b_raw).strip():
        return None
    da = _parse_publish_date(str(a_raw))
    db = _parse_publish_date(str(b_raw))
    if da == datetime.min or db == datetime.min:
        return None
    ad = da.date()
    bd = db.date()
    if ad > bd:
        return 1
    if ad < bd:
        return -1
    return 0


def _kap_pdr_requires_full_fetch(
    sess: requests.Session,
    cached_block: Optional[Dict[str, Any]],
) -> bool:
    """True: TEFAS+PDF tam adimi gerekli. False: mevcut JSON blogu yeterli."""
    if not cached_block:
        return True
    dur = cached_block.get("hisse_durumu")
    if dur == "uygun_degil":
        return False
    if dur != "ok":
        return True
    lk = str(cached_block.get("kap_link") or "").strip()
    if not lk:
        return True
    latest = _kap_newest_pdr_publish_raw(sess, lk)
    if latest is None:
        return True
    stored = cached_block.get("kap_rapor_tarihi")
    cmp = _pdr_publish_date_cmp(latest, str(stored) if stored is not None else "")
    if cmp is None:
        return True
    return cmp > 0


def _fetch_file_id_from_disclosure_page(sess: requests.Session, disclosure_index: Any) -> Optional[str]:
    """Geriye uyumluluk: ilk file_id'yi dondurur. Yeni kod _list_disclosure_attachments kullanmali."""
    atts = _list_disclosure_attachments(sess, disclosure_index)
    return atts[0]["file_id"] if atts else None


# Dosya adi pattern'leri:
#   '<KOD>_<YYYY.MM>.pdf'        -> ASIL PDR (Portfoy Dagilim Raporu)
#   '<KOD>_<YYYY.MM>A.pdf'       -> A* harfli ek (ay icindeki alis-satislar)
#   '<KOD>_<YYYY.MM> FTD.pdf'    -> Fon Toplam Deger ek raporu
#   'Endeks Korelasyon.pdf'      -> Endeks fonlarinin korelasyon raporu
#   '*FTD*' / 'AYLIK*' / 'BILDIRIM*' -> diger ekler
_PDR_FILENAME_RE = re.compile(
    r"^([A-Z0-9]{2,5})_(\d{4}\.\d{2})\.pdf$",
    re.IGNORECASE,
)


def _list_disclosure_attachments(
    sess: requests.Session, disclosure_index: Any
) -> List[Dict[str, Any]]:
    """KAP disclosure sayfasindaki tum file/download linklerini ve etiketlerini doner.
    Ekler liste icinde sayfa sirasiyla, her elemanda {file_id, label}.
    Etiket bulunamazsa label=None.
    """
    if not disclosure_index:
        return []
    r = _kap_request(sess, f"{KAP_DISCLOSURE_PAGE_URL}/{disclosure_index}", timeout=45)
    if r is None or not r.ok:
        return []
    text = r.text
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for m in re.finditer(r"file/download/([a-f0-9]{32})", text):
        fid = m.group(1)
        if fid in seen:
            continue
        seen.add(fid)
        # Etiket bul: yakinda <span ...>...</span> veya .pdf icerikli text
        ctx_start = max(0, m.start() - 600)
        ctx_end = min(len(text), m.end() + 200)
        ctx = text[ctx_start:ctx_end]
        label: Optional[str] = None
        for lm in re.finditer(r">([^<>\n]{4,120})</", ctx):
            cand = lm.group(1).strip()
            if cand.lower().endswith(".pdf"):
                label = cand
                break
        out.append({"file_id": fid, "label": label})
    return out


def _pick_pdr_attachment(
    attachments: List[Dict[str, Any]], kod: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Eklerini PDR olma olasiligina gore yuksekten dusugune sirala.
    1) '<KOD>_<YYYY.MM>.pdf' (suffix'siz, en olasi) en basa
    2) Label'da 'PDR' / 'PORTF' / 'DAGI'/'DAĞI' / 'DAGIL'/'DAĞIL' geçen
    3) FTD / A / Endeks Korelasyon vb. en sona
    Liste sirasi korunur (stable sort).
    """
    kod_up = (kod or "").strip().upper()

    def score(att: Dict[str, Any]) -> int:
        label = (att.get("label") or "").strip()
        up = label.upper()
        # Best: '<KOD>_<YYYY.MM>.pdf' veya kod ile baslayan '_YYYY.MM.pdf'
        m = _PDR_FILENAME_RE.match(label)
        if m and (not kod_up or m.group(1).upper() == kod_up):
            return 100
        if m:
            return 90
        # Iyi: PDR/PORTFOY/DAGILIM iceriyor ve A/FTD eki yok
        bad_suffix = bool(re.search(r"_(\d{4}\.\d{2})A\.pdf$", label, re.IGNORECASE))
        bad_suffix = bad_suffix or " FTD" in up or "ENDEKS KORELASYON" in up
        if not bad_suffix and (
            "PDR" in up
            or "PORTF" in up
            or "DAGI" in up
            or "DAĞI" in up
            or "DAGIL" in up
            or "DAĞIL" in up
        ):
            return 60
        # Kotu (genelde ek belge)
        if " FTD" in up or "ENDEKS KORELASYON" in up:
            return 5
        if re.search(r"_(\d{4}\.\d{2})A\.pdf$", label, re.IGNORECASE):
            return 5
        # Bilinmeyen (label yok dahil): sonradan denenebilir
        return 30

    return sorted(attachments, key=score, reverse=True)


def _download_kap_pdf(sess: requests.Session, file_id: str) -> Optional[bytes]:
    r = _kap_request(sess, f"{KAP_FILE_DOWNLOAD_URL}/{file_id}", timeout=60)
    if r is None or not r.ok:
        return None
    data = r.content
    i = data.find(b"%PDF-")
    return data[i:] if i >= 0 else None


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


# Ziraat 'AYLIK RAPOR' formatinda 'A - HISSE SENETLERI' bolumu
_ZIRAAT_TEMPLATE_RE = re.compile(
    r"AYLIK\s+RAPOR.*?FONU\s+TANITICI\s+B[İI]LG[İI]LER", re.DOTALL | re.IGNORECASE
)
_ZIRAAT_BLOCK_START_RE = re.compile(
    r"3\s*-\s*FON\s+PORTF[ÖO]Y\s+DE[ĞG]ER[İI]\s+TABLOSU.*?A\s*-\s*H[İI]SSE\s+SENETLER[İI]",
    re.IGNORECASE | re.DOTALL,
)
_ZIRAAT_BLOCK_END_RE = re.compile(
    r"\n\s*B\s*-\s*[A-ZÇĞİÖŞÜ][A-ZÇĞİÖŞÜ ]{3,}",
    re.IGNORECASE,
)
_ZIRAAT_ROW_RE = re.compile(
    r"^\s*\d{1,3}\s+([A-Z0-9]{2,6})\.E\s+.+?\s+"
    r"([\d.]+,\d{1,3})\s+"        # Nominal
    r"([\d.]+,\d{1,4})\s+"        # Rayic Deger
    r"(-?\d{1,3},\d{1,6})\s+"     # Oran (%)
    r"([\d.]+,\d{1,4})\s*$",      # Birim Alis Fiyati
    re.MULTILINE,
)


def _extract_hisse_rows_ziraat(pdf_bytes: bytes) -> List[Dict[str, Any]]:
    """Ziraat AYLIK RAPOR formatli PDF'lerden hisse listesi cikar."""
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return []
    text = "".join(p.get_text("text") + "\n" for p in doc)
    if not _ZIRAAT_TEMPLATE_RE.search(text):
        return []
    m = _ZIRAAT_BLOCK_START_RE.search(text)
    if not m:
        return []
    sub = text[m.end():]
    me = _ZIRAAT_BLOCK_END_RE.search(sub)
    if me:
        sub = sub[:me.start()]
    rows_by_ticker: Dict[str, float] = {}
    for r in _ZIRAAT_ROW_RE.finditer(sub):
        ticker = r.group(1)
        if ticker in _TICKER_BLACKLIST:
            continue
        try:
            oran = float(r.group(4).replace(",", "."))
        except ValueError:
            continue
        if not (0 < oran <= 50):
            continue
        rows_by_ticker[ticker] = rows_by_ticker.get(ticker, 0.0) + oran
    out = [
        {"ticker": tk, "ad": "", "agirlik": round(p, 4)}
        for tk, p in rows_by_ticker.items()
    ]
    out.sort(key=lambda r: -r["agirlik"])
    return out


def _pdf_is_image_only(pdf_bytes: bytes) -> bool:
    """PDF'in metin katmani yok mu? (Tarama veya sadece imge)"""
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return False
    total = sum(len(p.get_text("text").strip()) for p in doc)
    return total < 50  # neredeyse hicbir text yok


_RAPID_OCR_ENGINE: Any = None  # lazy singleton


def _get_rapidocr() -> Any:
    """RapidOCR engine'ini tek seferlik baslat (lazy)."""
    global _RAPID_OCR_ENGINE
    if _RAPID_OCR_ENGINE is not None:
        return _RAPID_OCR_ENGINE
    try:
        from rapidocr_onnxruntime import RapidOCR  # type: ignore
        _RAPID_OCR_ENGINE = RapidOCR()
    except Exception:
        _RAPID_OCR_ENGINE = False
    return _RAPID_OCR_ENGINE


def _pdf_ocr_text(pdf_bytes: bytes, dpi: int = 220) -> str:
    """PDF sayfa goruntulerini PyMuPDF ile rasterize et, RapidOCR ile metne cevir.

    Once Tesseract (PyMuPDF integration) denenir; kurulu degilse RapidOCR'a duser.
    Hicbiri yoksa "" doner.
    """
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return ""

    # 1) Tesseract (PyMuPDF integration)
    try:
        parts: List[str] = []
        for page in doc:
            tp = page.get_textpage_ocr(dpi=dpi, language="tur+eng", full=True)
            parts.append(page.get_text("text", textpage=tp))
        joined = "\n".join(parts).strip()
        if joined:
            return joined
    except Exception:
        pass

    # 2) RapidOCR (ONNX) — Windows'ta Tesseract yok ise
    engine = _get_rapidocr()
    if not engine:
        return ""
    parts2: List[str] = []
    try:
        # PIL DecompressionBomb guard'ini buyuk PDF sayfalari icin kapat
        try:
            from PIL import Image as _Img  # type: ignore
            _Img.MAX_IMAGE_PIXELS = None
        except Exception:
            pass
        zoom = dpi / 72.0
        mat = pymupdf.Matrix(zoom, zoom)
        for page in doc:
            pix = page.get_pixmap(matrix=mat, alpha=False)
            png = pix.tobytes("png")
            try:
                import io
                from PIL import Image
                import numpy as np
                im = Image.open(io.BytesIO(png)).convert("RGB")
                arr = np.array(im)
            except Exception:
                continue
            try:
                result, _ = engine(arr)
            except Exception:
                continue
            if not result:
                continue
            # result: [[box, text, conf], ...]
            # Y'ye gore satira topla
            items = []
            for r in result:
                box = r[0]; txt = r[1]; conf = r[2]
                ys = [p[1] for p in box]; xs = [p[0] for p in box]
                items.append((sum(ys)/4, sum(xs)/4, txt))
            items.sort(key=lambda t: (round(t[0]/8), t[1]))
            line_y = None; current_line: List[str] = []
            for y, x, t in items:
                yk = round(y / 8)
                if line_y is None or yk == line_y:
                    current_line.append(t); line_y = yk
                else:
                    parts2.append(" ".join(current_line))
                    current_line = [t]; line_y = yk
            if current_line:
                parts2.append(" ".join(current_line))
            parts2.append("")  # sayfa ayrac
    except Exception:
        pass
    return "\n".join(parts2).strip()


# ISIN-bazli OCR parser yardimcilari
_OCR_NUMBER_RE = re.compile(r"^-?\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,6})?$")
_OCR_PCT_RE = re.compile(r"^-?\d{1,3}[.,]\d{1,4}$")
_OCR_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9]{2,5}$")
# Sadece BIST hisse ISIN'leri (TRA / TRE). TRD = hazine bonosu, TRY = fon -> haric.
_OCR_STOCK_ISIN_RE = re.compile(r"^TR[AE][A-Z0-9]{9}$")

# Bilinen BIST ticker seti (data/_known_tickers.txt) - fused token'da
# dogru ticker uzunlugunu secmek icin kullanilir.
_KNOWN_TICKERS_CACHE: Optional[frozenset] = None


def _get_known_tickers() -> frozenset:
    global _KNOWN_TICKERS_CACHE
    if _KNOWN_TICKERS_CACHE is not None:
        return _KNOWN_TICKERS_CACHE
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "data", "_known_tickers.txt")
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                items = {ln.strip() for ln in fh if ln.strip()}
            _KNOWN_TICKERS_CACHE = frozenset(items)
            return _KNOWN_TICKERS_CACHE
        except Exception:
            pass
    _KNOWN_TICKERS_CACHE = frozenset()
    return _KNOWN_TICKERS_CACHE
# Yanlis pozitif kelimeler (sektor adlari, sirket adi parcalari, basliklar...)
_OCR_WORD_BLACKLIST = frozenset({
    # Tablo basliklari / sayfa metni
    "TARIH", "AYLIK", "YILLIK", "GORE", "ORANI", "ARTIS", "FIYAT", "FIYATI",
    "HISSE", "SENEDI", "NOMINAL", "RAYIC", "DEGER", "DEGERI",
    "TUTAR", "TUTARI", "GRUP", "TOPLAM", "PORTFOY", "FON", "FONU", "FONUN",
    "ARACLAR", "ARACLARI", "ISIN", "KODU", "ALIS", "SATIS", "ALIM", "SATIM",
    "BANKA", "TPP", "REPO", "MEVDUAT", "MENKUL", "PAY", "PAYI", "BORC",
    "BORCLAR", "ALACAK", "ALACAKLAR", "VARLIK", "VARLIKLAR",
    "PDF", "TL", "TRY", "USD", "EUR", "GES", "GOS", "SWAP", "BYF",
    # Sektor / sirket isim parcalari (sirket adlarinda yaygin gecen
    # cogul/tekil Turkce kelimeler — OCR ticker konumuna kayabiliyor)
    "SANAYI", "TICARET", "TIC", "HOLDING", "HOLDIN", "HOLDiN",
    "GIDA", "KAGIT", "ENERJI", "ENERJ", "DEMIR", "DEMIRCELIK",
    "BANKASI", "BANKAS", "HAZINE", "TAAHHUT", "PIYASA", "PIYASASI",
    "GAYRIMENKUL", "GAYRiMENKUL", "YATIRIM", "YATIRIMLARI", "ORTAKLIGI",
    "TEKNOLOJI", "TEKNOLOJ", "TEKSTIL", "OTOMOTIV", "INSAAT",
    "ELEKTRIK", "ELEKTRONIK", "GUBRE", "PETROL", "RAFINERI",
    "KIMYA", "ILAC", "MADEN", "MADENI", "CIMENTO", "CELIK",
    "TURIZM", "TARIM", "DAGITIM", "TASIMACILIK", "PERAKENDE",
    # Diger genel kelimeler
    "BLUE", "NET", "KOC", "HALK", "TURK", "TURKIYE", "MAGAZALAR",
    "ALTIN", "GUMUS", "BAKIR", "VOB", "VIOP",
})


def _ocr_to_pct(token: str) -> Optional[float]:
    """OCR token'i yuzde degerine cevir. '4.30' / '4,30' / '4.30%' -> 4.30
    1.000.000 gibi binlik ayraclilar reddedilir.
    """
    t = token.replace("%", "").strip()
    if not _OCR_PCT_RE.match(t):
        return None
    try:
        v = float(t.replace(",", "."))
    except ValueError:
        return None
    if 0 < v <= 50:
        return v
    return None


def _extract_hisse_rows_ocr(pdf_bytes: bytes) -> List[Dict[str, Any]]:
    """Image-only PDF'lerde OCR ile metni cikar, ISIN-bazli parser'la hisse listesi olustur.

    Yontem:
      1) Once Ziraat template'i dene (text varsa Ziraat seyrek ama OCR icin de calismayi
         garantiler).
      2) ISIN bazli generic parser: her satirda ISIN bulunursa solda en yakin ticker'i
         al, ISIN'den sonraki numeric token'lar arasindan SON yuzde degerini (Toplam %)
         oran olarak al.
      3) Cok satira yayilan kayitlar icin: pencereli kaydirma ile sonraki 1-2 satirin
         tail'inden de oran arariz.
    """
    text = _pdf_ocr_text(pdf_bytes)
    if not text:
        return []

    # 1) Ziraat
    if _ZIRAAT_TEMPLATE_RE.search(text):
        m = _ZIRAAT_BLOCK_START_RE.search(text)
        if m:
            sub = text[m.end():]
            me = _ZIRAAT_BLOCK_END_RE.search(sub)
            if me: sub = sub[:me.start()]
            rows_by_ticker: Dict[str, float] = {}
            for r in _ZIRAAT_ROW_RE.finditer(sub):
                tk = r.group(1)
                if tk in _TICKER_BLACKLIST: continue
                try: o = float(r.group(4).replace(",", "."))
                except ValueError: continue
                if 0 < o <= 50:
                    rows_by_ticker[tk] = rows_by_ticker.get(tk, 0.0) + o
            if rows_by_ticker:
                out = [{"ticker": k, "ad": "", "agirlik": round(v, 4)} for k, v in rows_by_ticker.items()]
                out.sort(key=lambda r: -r["agirlik"]); return out

    # 2) ISIN-bazli generic OCR parser
    # PDR satir formati genellikle:
    #   <TICKER> <SIRKET_ADI...> <ISIN> <Nominal> <ToplamDeger> <Grup%> <Toplam%>
    # Ama OCR sirasinda token'lar bazen birlesir/bozulur:
    #   - "ALBRKALBARAKATURKKATILIMBANKASITREALBKOOO11" gibi fused token,
    #     bu durumda yuzdeler ONCEKI satirda kalir.
    #   - Veya percentages bir sonraki satira tasinabilir.
    # ISIN sadece TRA/TRE prefix'li hisse ISIN'i olmali (TRD = hazine, TRY = fon
    # haric).
    def _first_valid_ticker(tokens: List[str]) -> Optional[str]:
        for tk in tokens:
            tk = tk.strip(":,;()")
            if (
                _OCR_TICKER_RE.match(tk)
                and tk not in _TICKER_BLACKLIST
                and tk not in _OCR_WORD_BLACKLIST
            ):
                return tk
        return None

    def _pct_candidates(tokens: List[str]) -> List[float]:
        out: List[float] = []
        for t in tokens:
            p = _ocr_to_pct(t)
            if p is not None:
                out.append(p)
        return out

    lines = text.splitlines()
    rows_by_ticker: Dict[str, float] = {}

    # Stock ISIN'i bir token'in ICINDE de bulabilir, sondaysa ticker prefix'i
    # cikar. Ornek: ALBRKALBARAKATURKKATILIMBANKASITREALBKOOO11
    _ISIN_SUBSTR = re.compile(r"(TR[AE][A-Z0-9]{9})(?![A-Z0-9])")
    known = _get_known_tickers()

    def _extract_fused_ticker(prefix: str) -> Optional[str]:
        """ALBRKALBARAKATURK... -> 'ALBRK'. Once 5/4/6/3 uzunlukta dene,
        bilinen ticker setinde ilk eslesen kazanir; setsiz fallback: 5 char."""
        if not prefix or not prefix[0].isalpha():
            return None
        # blacklist filtreli adaylari topla
        candidates: List[str] = []
        for tlen in (5, 4, 6, 3):
            if len(prefix) <= tlen:
                continue
            cand = prefix[:tlen]
            if (
                _OCR_TICKER_RE.match(cand)
                and cand not in _TICKER_BLACKLIST
                and cand not in _OCR_WORD_BLACKLIST
            ):
                candidates.append(cand)
        if not candidates:
            return None
        if known:
            for c in candidates:
                if c in known:
                    return c
        return candidates[0]

    for li, line in enumerate(lines):
        toks = line.split()
        if not toks:
            continue

        isin_idx: Optional[int] = None
        fused_ticker: Optional[str] = None
        for i, t in enumerate(toks):
            if _OCR_STOCK_ISIN_RE.match(t):
                isin_idx = i
                break
            m_isin = _ISIN_SUBSTR.search(t)
            if m_isin and m_isin.end() >= len(t) - 1:
                # ISIN bu token'in sonunda — isin_idx'i her halukarda set et
                # (fused ticker extraction basarisiz olsa bile, ticker
                # ONCEKI token'larda bulunabilir).
                isin_idx = i
                cand = _extract_fused_ticker(t[: m_isin.start()])
                if cand:
                    fused_ticker = cand
                break
        if isin_idx is None:
            continue

        # Ticker secimi: SCORE-BAZLI. Her aday icin guvenirlik skoru hesaplanir,
        # en yuksek skorlu kazanir. Bu sayede "KNOWN exact" ile "ISIN body
        # korroborasyonu" arasindaki onceligi dogru sekilde yonetebiliriz.
        #
        # Skorlar:
        #   100 = ISIN body kendisi known ticker (KANONIK: TUPRS, EKGYO body=ticker)
        #    90 = KNOWN exact + body korroborasyonu (token in known + body[:4-5] eslesme)
        #    80 = KNOWN prefix-of-fused + body korroborasyonu
        #    75 = Body corroboration sadece (token prefix match, token in known degil)
        #    70 = Fused-with-ISIN + body korroborasyonu (ALBRKALBARAKA->ALBRK)
        #    65 = KNOWN exact (body korroborasyonu yok ama token in known)
        #    60 = KNOWN prefix-of-fused (no body corrob)
        #    55 = Fused-with-ISIN in known (no body corrob)
        #    50 = Fused-with-ISIN, only known set bos (no validation needed)
        #    45 = Generic alpha token (3-6 char, OCR_TICKER pattern)
        #    40 = Generic from previous line
        #    35 = Forward-look matched
        #    30 = ISIN body alpha fallback (son care)
        ticker: Optional[str] = None

        # ISIN string'i bir kere cikar.
        isin_str: Optional[str] = None
        tk_at_isin = toks[isin_idx].strip(":,;()")
        if _OCR_STOCK_ISIN_RE.match(tk_at_isin):
            isin_str = tk_at_isin
        else:
            m_isin2 = _ISIN_SUBSTR.search(tk_at_isin)
            if m_isin2:
                isin_str = m_isin2.group(1)
        body: str = isin_str[3:] if isin_str else ""

        def _body_corroborates(tk_str: str) -> bool:
            if not body or not tk_str:
                return False
            tk_up = tk_str.upper()
            for n in (5, 4, 6):
                if len(tk_up) >= n and len(body) >= n and tk_up[:n] == body[:n]:
                    return True
            return False

        cand_list: List[Tuple[int, str]] = []  # (score, ticker)

        # 100) Body kendisi known ticker
        if known and body:
            for tlen in (5, 4, 6):
                cand = body[:tlen]
                if (
                    _OCR_TICKER_RE.match(cand)
                    and cand in known
                    and cand not in _TICKER_BLACKLIST
                    and cand not in _OCR_WORD_BLACKLIST
                ):
                    cand_list.append((100, cand))
                    break

        # 65/90) KNOWN exact in toks before ISIN
        for tk in toks[:isin_idx]:
            tk2 = tk.strip(":,;()")
            if (
                known
                and tk2 in known
                and tk2 not in _TICKER_BLACKLIST
                and tk2 not in _OCR_WORD_BLACKLIST
            ):
                cand_list.append((90 if _body_corroborates(tk2) else 65, tk2))

        # 60/80) KNOWN prefix-of-fused in toks before ISIN (BORSKBORSEKE -> BORSK)
        for tk in toks[:isin_idx]:
            cand = _extract_fused_ticker(tk)
            if cand and known and cand in known:
                cand_list.append((80 if _body_corroborates(cand) else 60, cand))

        # 75) Body korroborasyonu (token in known degil, ama prefix orisme)
        if body:
            for tk in toks[:isin_idx]:
                tk_clean = tk.strip(":,;()")
                if not tk_clean or not tk_clean[0].isalpha():
                    continue
                tk_upper = tk_clean.upper()
                for tlen in (5, 4, 6):
                    if len(tk_upper) < tlen or len(body) < tlen:
                        continue
                    cand = body[:tlen]
                    if (
                        _OCR_TICKER_RE.match(cand)
                        and tk_upper.startswith(cand)
                        and cand not in _TICKER_BLACKLIST
                        and cand not in _OCR_WORD_BLACKLIST
                    ):
                        cand_list.append((75, cand))
                        break

        # 50/55/70) Fused with ISIN
        if fused_ticker is not None:
            if not known:
                cand_list.append((50, fused_ticker))
            elif fused_ticker in known:
                score = 70 if _body_corroborates(fused_ticker) else 55
                cand_list.append((score, fused_ticker))
            elif body and body.startswith(fused_ticker):
                cand_list.append((70, fused_ticker))

        # 45) Generic alpha
        gen = _first_valid_ticker(toks[:isin_idx])
        if gen is not None:
            cand_list.append((45, gen))

        # 40) Previous line: tam token veya fused prefix
        if li > 0:
            prev_toks = lines[li - 1].split()
            gen_prev = _first_valid_ticker(prev_toks)
            if gen_prev is not None:
                cand_list.append((40, gen_prev))
            else:
                # Fused prefix dene (PSGYOPASiFiK... -> PSGYO)
                for tk in prev_toks:
                    cand = _extract_fused_ticker(tk)
                    if cand:
                        cand_list.append((40, cand))
                        break

        # En yuksek skoru sec
        if cand_list:
            cand_list.sort(key=lambda c: -c[0])
            ticker = cand_list[0][1]
        # Ileri-bakis: ISIN bir satirda YALNIZ ise (sadece ISIN token'i, baska
        # veri yok) sonraki satir cogunlukla bu row'un devami olur (OCR PDF'i
        # 2 satira bolmus). Ornek (NKT):
        #   line N:    "TREMLPC00021"  (ISIN tek basina)
        #   line N+1:  "MPARK MLP SAGLIK ... 11.305 4.810.277,50 9,58 8,81"
        # Bu durumda ticker=MPARK ve yuzdeler line N+1'den. ISIN body'sini
        # (MLPC) ticker olarak alirsak Pass 2'de MPARK ile cakisir, cifte sayim
        # olur. Bu yuzden forward-look SADECE bare-ISIN satirlarinda calisir.
        bare_isin = (len(toks) == 1 and isin_idx == 0)
        if ticker is None and bare_isin:
            for ahead in (1, 2):
                if li + ahead >= len(lines):
                    break
                ahead_toks = lines[li + ahead].split()
                # GUVENLIK: Ileri satirda baska bir ISIN varsa, oranlarini
                # buraya cekmeyelim - ayri row.
                ahead_has_isin = any(
                    _OCR_STOCK_ISIN_RE.match(t) for t in ahead_toks
                ) or any(
                    (mz := _ISIN_SUBSTR.search(t)) and mz.end() >= len(t) - 1
                    for t in ahead_toks
                )
                if ahead_has_isin:
                    break
                # Tam known ticker token'i
                if known:
                    for tk in ahead_toks:
                        tk2 = tk.strip(":,;()")
                        if (
                            tk2 in known
                            and tk2 not in _TICKER_BLACKLIST
                            and tk2 not in _OCR_WORD_BLACKLIST
                        ):
                            ticker = tk2
                            break
                if ticker is not None:
                    break
                # Fused token prefix known
                if known:
                    for tk in ahead_toks:
                        cand = _extract_fused_ticker(tk)
                        if cand and cand in known:
                            ticker = cand
                            break
                if ticker is not None:
                    break
        # Son care: bare-ISIN line'da forward-look bile basarisizsa, ISIN
        # body'sinden alpha prefix'i ticker olarak kullan (TRELIMK00029 -> LIMK).
        # SADECE bare-ISIN'a kisitliyiz cunku diger durumlarda score-based
        # picker yeterli sinyal uretir; bare'da hicbir baska sinyal kalmaz.
        if ticker is None and bare_isin and body:
            for tlen in (4, 5):
                cand = body[:tlen]
                if (
                    _OCR_TICKER_RE.match(cand)
                    and cand not in _TICKER_BLACKLIST
                    and cand not in _OCR_WORD_BLACKLIST
                ):
                    ticker = cand
                    break
        if ticker is None:
            continue

        # Yuzdeleri bul: once mevcut satirin ISIN'den sonrasi, sonra ileri
        # satirlar, sonra geri (fused durum icin). pcts_used_li: pct'lerin
        # geldigi satir (yoksa None).
        pcts_used_li: Optional[int] = None
        pcts = _pct_candidates(toks[isin_idx + 1:])
        if pcts:
            pcts_used_li = li
        if not pcts and li + 1 < len(lines):
            pcts = _pct_candidates(lines[li + 1].split())
            if pcts: pcts_used_li = li + 1
        if not pcts and li + 2 < len(lines):
            pcts = _pct_candidates(lines[li + 2].split())
            if pcts: pcts_used_li = li + 2
        if not pcts and li > 0:
            pcts = _pct_candidates(lines[li - 1].split())
            if pcts: pcts_used_li = li - 1
        if not pcts:
            continue
        # COKLU SATIR DEVAMI: Eger sadece 1 yuzde aday'i varsa (genellikle
        # Group%), bir sonraki satirin tek-token-pct olup olmadigina bak;
        # varsa Total% olarak ekle. Ornek (NKT TAPD):
        #   line N+1: "55.985,000 1.203.677,50 2,40"  -> Group%=2.40
        #   line N+2: "2,20"                            -> Total%=2.20
        if len(pcts) == 1:
            for k in (1, 2):
                if li + k >= len(lines):
                    continue
                cont = lines[li + k].split()
                if len(cont) == 1 and not _OCR_STOCK_ISIN_RE.match(cont[0]):
                    p2 = _ocr_to_pct(cont[0])
                    if p2 is not None and p2 != pcts[0]:
                        pcts.append(p2)
                        if pcts_used_li is None or li + k > pcts_used_li:
                            pcts_used_li = li + k
                        break
        oran = pcts[-1]  # Toplam(%)
        rows_by_ticker[ticker] = rows_by_ticker.get(ticker, 0.0) + oran

        # COKLU ROW DEVAMI: Bir hisse senedi PDR'de birden cok satirda
        # gorunebilir (alimlar/satimlar, A.grup/B.grup, vs). OCR bu satirlari
        # bazen bolup ticker bilgisini kaybedebilir. Pcts'lerden sonra (eger
        # pure numeric satirda 2+ pct varsa) AYNI ticker'a ekle.
        # Ornek (NKT TUPRS row 3): line 103 = "114.081,000 4.916.891,10 9,79 9,00"
        # -> TUPRS += 9.00
        scan_from = (pcts_used_li if pcts_used_li is not None else li) + 1
        scan_to = min(scan_from + 4, len(lines))
        for ki in range(scan_from, scan_to):
            cont_toks = lines[ki].split()
            if not cont_toks:
                break  # bos satir multi-row'u bitirir
            # ISIN goren herhangi bir token: yeni row baslangici, dur
            if any(_OCR_STOCK_ISIN_RE.match(t) for t in cont_toks):
                break
            if any(
                (mz := _ISIN_SUBSTR.search(t)) and mz.end() >= len(t) - 1
                for t in cont_toks
            ):
                break
            # Alpha-baslayan token: muhtemelen yeni ticker satiri, dur
            if any(t and t[0].isalpha() for t in cont_toks):
                break
            # Pure numeric satir: 2+ yuzde aday'i varsa multi-row continuation
            cont_pcts = _pct_candidates(cont_toks)
            if len(cont_pcts) >= 2:
                rows_by_ticker[ticker] = rows_by_ticker.get(ticker, 0.0) + cont_pcts[-1]

    # 3) ISIN-siz known-ticker fallback:
    # OCR bazi entry'lerde ISIN'i hic yakalamayabilir (ornek NKT'de EDIP).
    # Onceki gecisten yakalanmamis known ticker'lari, satirinda 2+ yuzde
    # adayi varsa ekle (EDIP / 21.000,000 698.880,00 1,39 1,28 gibi).
    if known:
        for li, line in enumerate(lines):
            toks = line.split()
            if not toks:
                continue
            # Bu satirda ISIN var mi? Varsa zaten yukarida islendi -> atla.
            if any(_OCR_STOCK_ISIN_RE.match(t) for t in toks):
                continue
            if any(
                (m := _ISIN_SUBSTR.search(t)) and m.end() >= len(t) - 1
                for t in toks
            ):
                continue
            # Ilk known ticker'i bul; 0 veya 1 inci pozisyonda olmali ki
            # rastgele baska bir satirda ki ticker'i yakalamayalim.
            ticker_here: Optional[str] = None
            for j, tk in enumerate(toks[:2]):
                tk2 = tk.strip(":,;()")
                if (
                    tk2 in known
                    and tk2 not in _TICKER_BLACKLIST
                    and tk2 not in _OCR_WORD_BLACKLIST
                    and tk2 not in rows_by_ticker  # tekrar saymayalim
                ):
                    ticker_here = tk2
                    break
            if ticker_here is None:
                continue
            # Mevcut satirda %2+ yuzde aday yoksa ileri satira bak.
            pcts_here = _pct_candidates(toks)
            if len(pcts_here) < 2 and li + 1 < len(lines):
                nxt = lines[li + 1].split()
                # Ileri satir yeni bir row baslangici olmamali
                if any(_OCR_STOCK_ISIN_RE.match(t) for t in nxt):
                    continue
                if any(
                    (m := _ISIN_SUBSTR.search(t)) and m.end() >= len(t) - 1
                    for t in nxt
                ):
                    continue
                pcts_here = _pct_candidates(nxt)
            # En az 2 yuzde aday istiyoruz (Group% Total%).
            # Tekli %li satirlar genellikle ozet/genel toplam.
            if len(pcts_here) < 2:
                continue
            oran = pcts_here[-1]
            rows_by_ticker[ticker_here] = rows_by_ticker.get(ticker_here, 0.0) + oran

    out = [{"ticker": k, "ad": "", "agirlik": round(v, 4)} for k, v in rows_by_ticker.items()]
    out.sort(key=lambda r: -r["agirlik"])
    return out


def extract_hisse_rows_from_pdr_pdf(pdf_bytes: bytes) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    PDR tablo ayıklama (3 strateji sirayla):
    1) Klasik (TEFAS + Yeni Format) - PyMuPDF words, %li satirlar
    2) Ziraat 'AYLIK RAPOR' template - 'A - HISSE SENETLERI' tablosu
    3) Image-only PDF (text=0) -> OCR (Tesseract) ardindan klasik/Ziraat parse

    Hicbiri donmezse 'Veri okunamadı'.
    """
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        return [], f"PDF açılamadı: {e}"

    # 0) Image-only ise direk OCR'a git
    if _pdf_is_image_only(pdf_bytes):
        rows = _extract_hisse_rows_ocr(pdf_bytes)
        if rows:
            return rows, None
        return [], "Veri okunamadı"

    # 1) Ziraat template'ini onceden dene (text-mode PDF'lerde)
    full_text = "".join(p.get_text("text") + "\n" for p in doc)
    if _ZIRAAT_TEMPLATE_RE.search(full_text):
        rows = _extract_hisse_rows_ziraat(pdf_bytes)
        if rows:
            return rows, None
        # Ziraat template ama parse failed -> klasik parser'i da dene

    if not _pdf_has_hisse_section(pdf_bytes):
        return [], "Veri okunamadı"

    rows_by_ticker: Dict[str, float] = {}

    for pi, page in enumerate(doc):
        words = page.get_text("words")
        if not words:
            continue
        # Y koordinatı yakın olan kelimeleri aynı satıra topla (3 px tolerans)
        bucket: Dict[int, List[Any]] = {}
        for w in words:
            yk = int(round(w[1] / 3.0))
            bucket.setdefault(yk, []).append(w)
        for yk in sorted(bucket.keys()):
            line_words = sorted(bucket[yk], key=lambda t: t[0])
            tokens = [t[4].strip() for t in line_words if t[4].strip()]
            if len(tokens) < 3:
                continue
            first = tokens[0]
            ticker = _normalize_ticker(first)
            if ticker is None or ticker in _TICKER_BLACKLIST:
                continue
            # Önce % sembolü içeren token'ı ara (AHI/MAC formatı)
            pct: Optional[float] = None
            for t in reversed(tokens):
                if _PCT_WITH_SYMBOL_RE.match(t):
                    p = _parse_pct(t)
                    if p is not None and 0 < p <= 50:
                        pct = p
                        break
            # % sembolü yoksa: satır gerçekten ana özet satırı mı (ISIN içeriyor mu) kontrol et
            if pct is None:
                has_isin = any(_ISIN_RE.match(tt) for tt in tokens[1:])
                if has_isin:
                    last = tokens[-1]
                    if _PCT_NO_SYMBOL_RE.match(last):
                        p = _parse_pct(last)
                        if p is not None and 0 < p <= 50:
                            pct = p
            if pct is None:
                continue
            rows_by_ticker[ticker] = rows_by_ticker.get(ticker, 0.0) + pct

    if not rows_by_ticker:
        return [], "Veri okunamadı"

    out = [
        {"ticker": tk, "ad": "", "agirlik": round(p, 4)}
        for tk, p in rows_by_ticker.items()
    ]
    out.sort(key=lambda r: -r["agirlik"])
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

    out["kap_rapor_tarihi"] = disclosures[0].get("publish_date")
    last_err: Optional[str] = None

    # Birden fazla disclosure denenebilir (en yeniden eskiye dogru, max 4 ay geri).
    # Bu image-only PDF veya bozuk dosya durumunda dayaniklilik saglar.
    for d_idx, disclosure in enumerate(disclosures[:4]):
        attachments = _list_disclosure_attachments(sess, disclosure.get("disclosure_index"))
        if not attachments:
            last_err = "KAP rapor eki bulunamadı."
            continue

        ranked = _pick_pdr_attachment(attachments, kod=kod)
        for a_idx, att in enumerate(ranked):
            file_id = att["file_id"]
            label = att.get("label") or "(no-label)"
            pdf_url = _pdf_download_url(file_id)
            if log:
                tag = (
                    "PDR" if (d_idx == 0 and a_idx == 0)
                    else f"alternatif (disclosure #{d_idx+1}, ek #{a_idx+1})"
                )
                print(
                    f"[KAP] {kod}: {tag} deneniyor — tarih: {disclosure.get('publish_date')!r}, "
                    f"label: {label}",
                    flush=True,
                )
            pdf = _download_kap_pdf(sess, file_id)
            if not pdf:
                last_err = "KAP rapor PDF indirilemedi."
                continue
            kaynak_pdr_ocr = _pdf_is_image_only(pdf)
            rows, err = apply_pdr_pdf_extraction(pdf)
            if rows:
                out["kap_pdf_url"] = pdf_url
                out["hisseler"] = rows
                out["hisse_durumu"] = "ok"
                out["hisse_mesaj"] = f"{len(rows)} hisse satırı okundu."
                if kaynak_pdr_ocr:
                    out["kaynak_pdr_ocr"] = True
                # Eger eski bir disclosure'dan geldiyse, kap_rapor_tarihi'ni guncelle
                out["kap_rapor_tarihi"] = disclosure.get("publish_date")
                if log:
                    print(
                        f"[KAP] {kod}: {len(rows)} adet hisse bulundu "
                        f"(disclosure #{d_idx+1}, ek: {label}).",
                        flush=True,
                    )
                return out
            last_err = err or "Veri okunamadı"
            if log:
                print(
                    f"[KAP] {kod}: ek '{label}' parse edilemedi ({last_err}); "
                    f"diger ekler/disclosure'lar denenecek.",
                    flush=True,
                )

    out["hisse_mesaj"] = last_err or "Veri okunamadı"
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
    if hisse_result.get("kaynak_pdr_ocr"):
        block["kaynak_pdr_ocr"] = True

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

    if block.get("hisse_durumu") == "ok":
        block["kap_son_kontrol_iso"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        block["kap_son_kontrol_tip"] = "pdr_guncellendi"
    else:
        block.pop("kap_son_kontrol_iso", None)
        block.pop("kap_son_kontrol_tip", None)
    return block


def _stamp_kap_incremental_skip(block: Dict[str, Any]) -> None:
    """GitHub Pazartesi kontrolunde yeni bildirim yok; Fon Hisse Detay icin kanit."""
    block["kap_son_kontrol_iso"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    block["kap_son_kontrol_tip"] = "yeni_yok"


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


def run_incremental(
    codes_in: List[str],
    *,
    delay_s: float,
    peek_delay_s: float,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """KAP'ta bildirim tarihi yenilenmis fonlar icin tam PDR çekimi; digerleri atlanır.

    Atlanan (yeni bildirim yok) fonlara kap_son_kontrol_* damgası eklenir; birlesik kayit hep yazilir.

    Donus:
      (birlesik_dict, ozet_satirlari)
    """
    codes: List[str] = []
    seen: set[str] = set()
    for c in codes_in:
        k = str(c).strip().upper()
        if k and k not in seen:
            seen.add(k)
            codes.append(k)

    sess = _session()
    old: Dict[str, Any] = {}
    if OUT_PATH.is_file():
        try:
            old = json.loads(OUT_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            old = {}
    old_fonlar: Dict[str, Any] = old.get("fonlar") or {}

    birlesik: Dict[str, Any] = {
        "aciklama": old.get("aciklama")
        or (
            "TEFAS meta + KAP Portföy Dağılım Raporu PDF'inden okunan gerçek hisse ağırlıkları."
        ),
        "guncelleme": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fonlar": {},
    }

    refresh: List[str] = []
    for i, kod in enumerate(codes):
        if i and peek_delay_s > 0:
            time.sleep(peek_delay_s)
        bl_old = old_fonlar.get(kod)
        if _kap_pdr_requires_full_fetch(sess, bl_old):
            refresh.append(kod)
            continue
        bl_copy = copy.deepcopy(bl_old)
        if bl_copy.get("hisse_durumu") == "ok":
            _stamp_kap_incremental_skip(bl_copy)
        birlesik["fonlar"][kod] = bl_copy
        _write_per_fund_json(kod, bl_copy)

    if not refresh:
        print(
            "[incremental] KAP bildirimi: yeni PDR yok (veya uygun_degil/atlandı); "
            "TEFAS/Playwright yok — kontrol damgası birleşik dosyaya işlendi.",
            flush=True,
        )
        ozet_kal = [_ozet_satir(k, birlesik["fonlar"][k]) for k in codes if k in birlesik["fonlar"]]
        return birlesik, ozet_kal

    print(f"[incremental] {len(refresh)}/{len(codes)} fon icin tam PDR/TEFAS yenileniyor.", flush=True)

    client = get_browser_client()
    BROWSER_REFRESH_EVERY = 25
    try:
        for ri, kod in enumerate(refresh):
            if ri and delay_s > 0:
                time.sleep(delay_s)
            if ri and ri % BROWSER_REFRESH_EVERY == 0:
                try:
                    print(f"[BROWSER] {ri} fondan sonra TEFAS oturumu yenileniyor...", flush=True)
                    client.restart()
                except Exception as e:
                    print(f"[BROWSER] yenileme hatası: {e}", flush=True)
            tefas = fetch_tefas_analyze(client, kod)
            hisse_result = fetch_real_hisse_rows(sess, kod, tefas, log=True)
            block = merge_one(kod, tefas, hisse_result)
            birlesik["fonlar"][kod] = block
            _write_per_fund_json(kod, block)
    finally:
        try:
            close_browser_client()
        except Exception:
            pass

    ozet = [_ozet_satir(k, birlesik["fonlar"][k]) for k in codes if k in birlesik["fonlar"]]
    return birlesik, ozet


def run(codes: List[str], delay_s: float = 2.0) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    sess = _session()
    client = get_browser_client()
    birlesik: Dict[str, Any] = {
        "aciklama": (
            "TEFAS meta + KAP Portföy Dağılım Raporu PDF'inden okunan gerçek hisse ağırlıkları."
        ),
        "guncelleme": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fonlar": {},
    }
    ozet: List[Dict[str, Any]] = []

    BROWSER_REFRESH_EVERY = 25
    try:
        for i, kod in enumerate(codes):
            kod = kod.strip().upper()
            if not kod:
                continue
            if i and delay_s:
                time.sleep(delay_s)
            if i and i % BROWSER_REFRESH_EVERY == 0:
                try:
                    print(f"[BROWSER] {i} fondan sonra TEFAS oturumu yenileniyor...", flush=True)
                    client.restart()
                except Exception as e:
                    print(f"[BROWSER] yenileme hatası: {e}", flush=True)
            tefas = fetch_tefas_analyze(client, kod)
            hisse_result = fetch_real_hisse_rows(sess, kod, tefas, log=True)
            block = merge_one(kod, tefas, hisse_result)
            birlesik["fonlar"][kod] = block
            _write_per_fund_json(kod, block)
            ozet.append(_ozet_satir(kod, block))
    finally:
        try:
            close_browser_client()
        except Exception:
            pass

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
    ap.add_argument(
        "--sadece-yeni-pdr",
        action="store_true",
        help=(
            "KAP portföy bildirimi en yeni publishDate ile fon_hisse_birlesik.json'daki kap_rapor_tarihi "
            "aynı/eskiyse tam TEFAS+PDF atlanır. Yeni bildirim yoksa da kontrol tarihi yazılır (Fon Hisse Detay)."
        ),
    )
    ap.add_argument(
        "--peek-delay",
        type=float,
        default=0.35,
        help="(--sadece-yeni-pdr) KAP istekleri arası saniye — rate limit uyumu (varsayılan 0.35)",
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
            print("Örnek: .venv\\Scripts\\python fon_hisse_scraper.py AAV ACC", file=sys.stderr)
            print("       .venv\\Scripts\\python fon_hisse_scraper.py --tum-manifest", file=sys.stderr)
            return 1

    DATA.mkdir(parents=True, exist_ok=True)

    if args.sadece_yeni_pdr:
        merged_inc, ozet = run_incremental(
            codes, delay_s=args.delay, peek_delay_s=args.peek_delay
        )
        with OUT_PATH.open("w", encoding="utf-8") as f:
            json.dump(merged_inc, f, ensure_ascii=False, indent=2)
        print(f"Yazıldı: {OUT_PATH} (incremental, {len(merged_inc.get('fonlar') or {})} fon)", flush=True)
        print(f"Fon başı dosya: {DATA / '<KOD>_hisse_pdr.json'}", flush=True)
        _print_ozet_tablo(ozet)
        return 0

    birlesik, ozet = run(codes, delay_s=args.delay)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(birlesik, f, ensure_ascii=False, indent=2)
    print(f"Yazıldı: {OUT_PATH} ({len(birlesik['fonlar'])} fon)", flush=True)
    print(f"Fon başı dosya: {DATA / '<KOD>_hisse_pdr.json'}", flush=True)
    _print_ozet_tablo(ozet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
