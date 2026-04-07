#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fon Hisse Detay — TEFAS Fon Analiz API + manuel hisse listesi birleştirme.

TEFAS GetAllFundAnalyzeData:
  - fundAllocation: varlık sınıfı (Hisse Senedi %, Repo %, …) — hisse bazlı değil.
  - fundInfo / fundProfile: fon meta (ünvan, KAP linki).

Tek tek hisse ağırlıkları resmi TEFAS JSON'unda yok; bu script:
  1) Canlı TEFAS'tan varlık dağılımı + meta çeker.
  2) data/fon_hisse_portfoy.json içindeki manuel `hisseler` listesini aynen birleştirir.

Kullanım:
  pip install requests
  py fon_hisse_scraper.py IDH AAV
  py fon_hisse_scraper.py --tum-manifest    # manifest.json'daki tüm kodlar (yavaş)

Çıktı: data/fon_hisse_birlesik.json
"""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
MANUAL_PATH = DATA / "fon_hisse_portfoy.json"
OUT_PATH = DATA / "fon_hisse_birlesik.json"
MANIFEST_PATH = DATA / "manifest.json"

TEFAS_ANALYZE = "https://www.tefas.gov.tr/api/DB/GetAllFundAnalyzeData"

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


def _load_manual() -> Dict[str, Any]:
    if not MANUAL_PATH.is_file():
        return {"fonlar": {}}
    try:
        with MANUAL_PATH.open(encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"fonlar": {}}


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


def merge_one(
    kod: str,
    tefas: Optional[Dict[str, Any]],
    manual_entry: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    kod = kod.strip().upper()
    out: Dict[str, Any] = {
        "kod": kod,
        "guncelleme": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "kaynak_tefas": tefas is not None,
        "unvan": None,
        "kap_link": None,
        "varlik_dagilimi": [],
        "hisseler": [],
    }

    if manual_entry:
        out["hisseler"] = list(manual_entry.get("hisseler") or [])
        if manual_entry.get("not"):
            out["not"] = manual_entry.get("not")

    if tefas:
        fi = (tefas.get("fundInfo") or [{}])[0]
        fp = (tefas.get("fundProfile") or [{}])[0]
        out["unvan"] = fi.get("FONUNVAN") or fp.get("FONUNVAN")
        out["kap_link"] = fp.get("KAPLINK")
        alloc = tefas.get("fundAllocation") or []
        for row in alloc:
            tip = (row.get("KIYMETTIP") or "").strip()
            try:
                oran = float(row.get("PORTFOYORANI") or 0)
            except (TypeError, ValueError):
                oran = 0.0
            if tip:
                out["varlik_dagilimi"].append({"tip": tip, "oran": round(oran, 4)})

    return out


def run(codes: List[str], delay_s: float = 0.35) -> Dict[str, Any]:
    manual = _load_manual()
    manual_fon = manual.get("fonlar") or {}
    sess = _session()
    birlesik: Dict[str, Any] = {
        "aciklama": (
            "TEFAS varlık dağılımı + manuel hisse listesi (fon_hisse_portfoy.json). "
            "Hisse bazlı oranlar TEFAS JSON'unda yok; manuel besleyin veya KAP'tan ekleyin."
        ),
        "guncelleme": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fonlar": {},
    }

    for i, kod in enumerate(codes):
        kod = kod.strip().upper()
        if not kod:
            continue
        if i and delay_s:
            time.sleep(delay_s)
        tefas = fetch_tefas_analyze(sess, kod)
        me = manual_fon.get(kod)
        if isinstance(me, dict):
            pass
        else:
            me = None
        birlesik["fonlar"][kod] = merge_one(kod, tefas, me)

    return birlesik


def main() -> int:
    ap = argparse.ArgumentParser(description="TEFAS + manuel hisse birleştirme")
    ap.add_argument("fonlar", nargs="*", help="Fon kodları (örn: IDH AAV)")
    ap.add_argument(
        "--tum-manifest",
        action="store_true",
        help="manifest.json'daki tüm fon kodlarını işle",
    )
    ap.add_argument("--delay", type=float, default=0.35, help="İstekler arası saniye")
    args = ap.parse_args()

    if args.tum_manifest:
        codes = _load_manifest_codes()
        if not codes:
            print("manifest.json bulunamadı veya fon yok.", file=sys.stderr)
            return 1
    else:
        codes = [c.upper() for c in args.fonlar if c.strip()]
        if not codes:
            print("Örnek: py fon_hisse_scraper.py IDH AAV ACC", file=sys.stderr)
            print("       py fon_hisse_scraper.py --tum-manifest", file=sys.stderr)
            return 1

    DATA.mkdir(parents=True, exist_ok=True)
    birlesik = run(codes, delay_s=args.delay)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(birlesik, f, ensure_ascii=False, indent=2)
    print(f"Yazıldı: {OUT_PATH} ({len(birlesik['fonlar'])} fon)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
