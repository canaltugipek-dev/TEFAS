#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TEFAS / FundTurkey — Hisse Senedi Yogun Fon (HSYF) kesfi ve tarihsel veri.

- Baslangicta BindComparisonFundReturns (tefas.gov.tr) ile tum YAT fonlari cekilir;
  "Hisse Senedi Semsiye Fonu" + (unvanda Yogun / EQUITY-INTENSIVE) ile HSYF filtrelenir.
- Her fon icin son N gun (varsayilan 1825) BindHistoryInfo ile parca parca indirilir.
- Cikti: data/<KOD>_tefas.json ve data/manifest.json

Kullanim:
  pip install requests yfinance pandas numpy
  py tefas_scraper.py                  # tum HSYF, 5 yil, data/ + manifest(stats)
  py tefas_scraper.py --liste          # sadece kod listesi
  py tefas_scraper.py --manifest-yenile
  py tefas_scraper.py MAC --gun 365    # tek fon
  py tefas_scraper.py --istatistik-atlama   # benchmark yuklemeden
"""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import time
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

try:
    import numpy as np
    import pandas as pd
    import yfinance as yf

    _HAS_ANALYTICS = True
except ImportError:
    np = None  # type: ignore
    pd = None  # type: ignore
    yf = None  # type: ignore
    _HAS_ANALYTICS = False
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager

# --- Sabitler ---
HISSE_SEMSIVE_AD = "Hisse Senedi Şemsiye Fonu"
COMPARISON_PATH = "/api/DB/BindComparisonFundReturns"
INFO_PATH = "/api/DB/BindHistoryInfo"
CHUNK_DAYS = 90
DEFAULT_GUN = 1825
EXPECTED_SPAN_DAYS = 1760  # ~5 yil (tatil toleransi)
TRADING_DAYS = 252
RISKSIZ_YILLIK_DEFAULT = 0.45  # Kullanici tanimi: yillik %45 (basit faiz -> gunluk bilesik)
STAT_PERIODS = ("6M", "YTD", "1Y", "3Y", "5Y")
TICKER_BIST100 = "XU100.IS"
TICKER_USDTRY = "USDTRY=X"
MIN_OBS_METRICS = 20

BASES_HISTORY: List[Tuple[str, str]] = [
    ("https://fundturkey.com.tr", "https://fundturkey.com.tr/TarihselVeriler.aspx"),
    ("https://www.tefas.gov.tr", "https://www.tefas.gov.tr/TarihselVeriler.aspx"),
]

BASE_COMPARISON = "https://www.tefas.gov.tr"
REF_COMPARISON = f"{BASE_COMPARISON}/FonKarsilastirma.aspx"

HEADERS_BASE = {
    "Connection": "keep-alive",
    "X-Requested-With": "XMLHttpRequest",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
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


def _make_session() -> requests.Session:
    session = requests.Session()
    try:
        ctx = ssl.create_default_context()
        ctx.options |= 0x4
        session.mount("https://", _LegacySSLAdapter(ctx))
    except Exception:
        pass
    return session


def _ensure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (OSError, ValueError, AttributeError):
                pass


def _norm_ascii_upper(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper()


def _is_hsyf_row(row: Dict[str, Any]) -> bool:
    tur = (row.get("FONTURACIKLAMA") or "").strip()
    if tur != HISSE_SEMSIVE_AD:
        return False
    u = row.get("FONUNVAN") or ""
    n = _norm_ascii_upper(u)
    if "YOGUN" in n:
        return True
    uu = u.upper()
    return "INTENSIVE" in uu and "EQUITY" in uu


def _fmt_tr(d: datetime) -> str:
    return d.strftime("%d.%m.%Y")


def _parse_iso(s: str) -> datetime:
    return datetime.strptime(s.strip(), "%Y-%m-%d")


def _parse_row_date(val: Any) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        sec = float(val) / 1000.0 if val > 1e12 else float(val)
        try:
            return datetime.fromtimestamp(sec)
        except (OSError, ValueError, OverflowError):
            return None
    s = str(val).strip()
    if not s:
        return None
    if s.isdigit() and len(s) >= 10:
        try:
            return datetime.fromtimestamp(int(s) / 1000.0)
        except (OSError, ValueError, OverflowError):
            pass
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            part = s[:10] if fmt == "%Y-%m-%d" and len(s) >= 10 and "-" in s[:10] else s
            return datetime.strptime(part, fmt)
        except ValueError:
            continue
    return None


def _row_date_sort_key(row: Dict[str, Any]) -> datetime:
    for k in ("TARIH", "tarih", "date", "DATE"):
        if k in row and row[k]:
            d = _parse_row_date(row[k])
            if d:
                return d
    return datetime.min


def _dedupe_by_date(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_day: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        d = _row_date_sort_key(row)
        if d == datetime.min:
            continue
        key = d.strftime("%Y-%m-%d")
        by_day[key] = row
    return [by_day[k] for k in sorted(by_day.keys())]


def _date_chunks(start: datetime, end: datetime) -> List[Tuple[datetime, datetime]]:
    chunks: List[Tuple[datetime, datetime]] = []
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=CHUNK_DAYS - 1), end)
        chunks.append((cur, chunk_end))
        cur = chunk_end + timedelta(days=1)
    return chunks


def _headers_for(base_root: str, referer: str) -> Dict[str, str]:
    h = dict(HEADERS_BASE)
    h["Origin"] = base_root
    h["Referer"] = referer
    return h


def _warmup(session: requests.Session, base_root: str, referer: str) -> None:
    try:
        session.get(
            base_root + "/",
            headers={"User-Agent": HEADERS_BASE["User-Agent"]},
            timeout=25,
        )
    except requests.RequestException:
        pass


def _post_json(
    session: requests.Session,
    url: str,
    data: Dict[str, str],
    referer: str,
    origin: str,
    retries: int = 4,
    pause: float = 1.8,
) -> Optional[Any]:
    h = dict(HEADERS_BASE)
    h["Origin"] = origin
    h["Referer"] = referer
    for attempt in range(retries):
        try:
            r = session.post(url, data=data, headers=h, timeout=120)
            r.raise_for_status()
            text = (r.text or "").strip()
            if not text:
                time.sleep(pause)
                continue
            return r.json()
        except (requests.RequestException, ValueError):
            time.sleep(pause * (attempt + 1))
    return None


def discover_hsyf_funds(session: requests.Session) -> List[Dict[str, str]]:
    """Aktif HSYF fon kodlari ve unvanlari."""
    url = BASE_COMPARISON + COMPARISON_PATH
    form = {
        "calismatipi": "2",
        "fontip": "YAT",
        "sfontur": "Tümü",
        "kurucukod": "",
        "fongrup": "",
        "bastarih": "Başlangıç",
        "bittarih": "Bitiş",
        "fonturkod": "",
        "fonunvantip": "",
        "strperiod": "1,1,1,1,1,1,1",
        "islemdurum": "1",
    }
    _warmup(session, BASE_COMPARISON, REF_COMPARISON)
    payload = _post_json(session, url, form, REF_COMPARISON, BASE_COMPARISON)
    if not payload:
        return []
    raw = payload.get("data")
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, str]] = []
    seen = set()
    for row in raw:
        if not _is_hsyf_row(row):
            continue
        kod = (row.get("FONKODU") or "").strip().upper()
        if not kod or kod in seen:
            continue
        seen.add(kod)
        out.append(
            {
                "fon_kodu": kod,
                "fon_unvan": (row.get("FONUNVAN") or "").strip() or kod,
            }
        )
    out.sort(key=lambda x: x["fon_kodu"])
    return out


def _post_history_chunk(
    session: requests.Session,
    base_root: str,
    referer: str,
    fonkod: str,
    bastarih: str,
    bittarih: str,
    fontip: str,
) -> Optional[List[Dict[str, Any]]]:
    url = base_root + INFO_PATH
    data = {
        "fontip": fontip,
        "bastarih": bastarih,
        "bittarih": bittarih,
        "fonkod": fonkod.upper(),
    }
    try:
        r = session.post(
            url,
            data=data,
            headers=_headers_for(base_root, referer),
            timeout=45,
        )
        r.raise_for_status()
        payload = r.json()
    except (requests.RequestException, ValueError):
        return None
    raw = payload.get("data")
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        return [raw]
    return []


def resolve_history_base(session: requests.Session) -> Tuple[str, str]:
    """Tarihsel API icin calisan taban URL."""
    end = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=7)
    a, b = start, end
    for base_root, referer in BASES_HISTORY:
        _warmup(session, base_root, referer)
        rows = _post_history_chunk(
            session, base_root, referer, "MAC", _fmt_tr(a), _fmt_tr(b), "YAT"
        )
        if rows is not None and len(rows) > 0:
            return base_root, referer
    return BASES_HISTORY[0]


def fetch_fund_history(
    session: requests.Session,
    base_root: str,
    referer: str,
    fonkod: str,
    start: datetime,
    end: datetime,
    fontip: str = "YAT",
    delay_sec: float = 0.32,
) -> List[Dict[str, Any]]:
    chunks = _date_chunks(start, end)
    merged: List[Dict[str, Any]] = []
    for a, b in chunks:
        rows = _post_history_chunk(
            session, base_root, referer, fonkod, _fmt_tr(a), _fmt_tr(b), fontip
        )
        if rows is None:
            break
        merged.extend(rows)
        time.sleep(delay_sec)
    merged = _dedupe_by_date(merged)
    merged.sort(key=_row_date_sort_key)
    return merged


def _span_days(rows: List[Dict[str, Any]]) -> int:
    if len(rows) < 2:
        return 0
    d0 = _row_date_sort_key(rows[0])
    d1 = _row_date_sort_key(rows[-1])
    if d0 == datetime.min or d1 == datetime.min:
        return 0
    return max(0, (d1 - d0).days)


def build_bundle(
    fon_kodu: str,
    fon_unvan: str,
    start: datetime,
    end: datetime,
    kaynak: str,
    rows: List[Dict[str, Any]],
    fontip: str = "YAT",
) -> Dict[str, Any]:
    span = _span_days(rows)
    if not rows:
        durum = "veri_eksik"
        neden = "cekim_basarisiz"
    elif span < EXPECTED_SPAN_DAYS:
        durum = "veri_eksik"
        neden = "bes_yildan_kisa"
    else:
        durum = "tam"
        neden = None
    return {
        "fon_kodu": fon_kodu,
        "fon_unvan": fon_unvan,
        "fontip": fontip,
        "baslangic": start.strftime("%Y-%m-%d"),
        "bitis": end.strftime("%Y-%m-%d"),
        "kaynak": kaynak,
        "kayit_sayisi": len(rows),
        "gun_kapsami": span,
        "durum_panel": durum,
        "neden": neden,
        "veri": rows,
    }


def _rows_to_close_series(rows: List[Dict[str, Any]]) -> Any:
    if not _HAS_ANALYTICS or not rows:
        return None
    pairs: List[Tuple[pd.Timestamp, float]] = []
    for row in rows:
        d = _row_date_sort_key(row)
        if d == datetime.min:
            continue
        p = None
        for k in ("FIYAT", "fiyat", "price"):
            v = row.get(k)
            if v is None or v == "" or v == "-":
                continue
            try:
                p = float(v)
            except (TypeError, ValueError):
                continue
            break
        if p is None or p <= 0:
            continue
        ts = pd.Timestamp(d.date())
        pairs.append((ts, p))
    if len(pairs) < 5:
        return None
    pairs.sort(key=lambda x: x[0])
    idx = [x[0] for x in pairs]
    vals = [x[1] for x in pairs]
    ser = pd.Series(vals, index=pd.DatetimeIndex(idx))
    return ser[~ser.index.duplicated(keep="last")].sort_index()


def _period_start(period: str, end: pd.Timestamp) -> pd.Timestamp:
    end = pd.Timestamp(end).normalize()
    if period == "6M":
        return end - pd.DateOffset(months=6)
    if period == "YTD":
        return pd.Timestamp(year=end.year, month=1, day=1)
    if period == "1Y":
        return end - pd.DateOffset(years=1)
    if period == "3Y":
        return end - pd.DateOffset(years=3)
    if period == "5Y":
        return end - pd.DateOffset(years=5)
    return end - pd.DateOffset(years=5)


def _yf_close_column(df: Any) -> Any:
    assert pd is not None
    c = df["Close"]
    if isinstance(c, pd.DataFrame):
        return c.iloc[:, 0]
    return c


def download_benchmark_series(
    start: datetime, end: datetime
) -> Tuple[Optional[Any], Optional[Any], Optional[str]]:
    """yfinance ile BIST100 ve USD/TL; (xu_ser, usd_ser, hata_mesaji)."""
    if not _HAS_ANALYTICS or yf is None:
        return None, None, "numpy/pandas/yfinance yuklu degil"
    try:
        s = pd.Timestamp(start.date()) - pd.Timedelta(days=7)
        e = pd.Timestamp(end.date()) + pd.Timedelta(days=2)
        xu = yf.download(TICKER_BIST100, start=s, end=e, progress=False, auto_adjust=False)
        usd = yf.download(TICKER_USDTRY, start=s, end=e, progress=False, auto_adjust=False)
        if xu is None or xu.empty:
            return None, None, "XU100 verisi bos"
        xs = _yf_close_column(xu).dropna()
        xs.index = pd.DatetimeIndex(pd.to_datetime(xs.index).date)
        us = None
        if usd is not None and not usd.empty:
            us = _yf_close_column(usd).dropna()
            us.index = pd.DatetimeIndex(pd.to_datetime(us.index).date)
        return xs, us, None
    except Exception as exc:
        return None, None, str(exc)


def _empty_stat_block() -> Dict[str, Optional[float]]:
    return {"sharpe": None, "sortino": None, "alpha": None, "max_drawdown": None}


def compute_period_stats(
    fund_close: Any,
    mkt_close: Any,
    period: str,
    rf_annual: float,
) -> Dict[str, Optional[float]]:
    assert np is not None and pd is not None
    out = _empty_stat_block()
    if fund_close is None or mkt_close is None or len(fund_close) < 5:
        return out
    end = fund_close.index.max()
    p0 = _period_start(period, end)
    f = fund_close.loc[fund_close.index >= p0].loc[:end].dropna()
    if len(f) < MIN_OBS_METRICS:
        return out
    m = mkt_close.reindex(f.index).ffill().bfill()
    ok = m.notna() & f.notna()
    f = f.loc[ok]
    m = m.loc[ok]
    if len(f) < MIN_OBS_METRICS:
        return out

    rf_d = (1.0 + rf_annual) ** (1.0 / TRADING_DAYS) - 1.0
    ret_f = f.pct_change().dropna()
    ret_m = m.pct_change().dropna()
    ix = ret_f.index.intersection(ret_m.index)
    ret_f = ret_f.loc[ix]
    ret_m = ret_m.loc[ix]
    if len(ret_f) < MIN_OBS_METRICS:
        return out

    excess = ret_f - rf_d
    std = float(excess.std(ddof=1))
    if std > 1e-12:
        out["sharpe"] = round(float(np.sqrt(TRADING_DAYS) * excess.mean() / std), 6)

    neg_exc = np.minimum(0.0, (ret_f - rf_d).values)
    ddev = float(np.sqrt(np.mean(neg_exc**2)))
    if ddev > 1e-12:
        out["sortino"] = round(float(np.sqrt(TRADING_DAYS) * excess.mean() / ddev), 6)

    xm = (ret_m - rf_d).values
    yv = (ret_f - rf_d).values
    mask = np.isfinite(xm) & np.isfinite(yv)
    if int(mask.sum()) >= MIN_OBS_METRICS:
        coef = np.polyfit(xm[mask], yv[mask], 1)
        alpha_d = float(coef[1])
        out["alpha"] = round(float((1.0 + alpha_d) ** TRADING_DAYS - 1.0), 6)

    px = f.astype(float) / float(f.iloc[0])
    peak = px.cummax()
    out["max_drawdown"] = round(float((px / peak - 1.0).min()), 6)

    return out


def build_fund_stats_map(
    fund_series: Any,
    xu_series: Any,
    rf_annual: float,
) -> Dict[str, Dict[str, Optional[float]]]:
    stats: Dict[str, Dict[str, Optional[float]]] = {}
    for p in STAT_PERIODS:
        stats[p] = compute_period_stats(fund_series, xu_series, p, rf_annual)
    return stats


def enrich_manifest_entries_with_stats(
    entries: List[Dict[str, Any]],
    data_dir: Path,
    rf_annual: float,
    skip: bool,
) -> Dict[str, Any]:
    """Her kaleme 'stats' ekler; benchmark ozetini dondurur."""
    meta: Dict[str, Any] = {
        "bist100_ticker": TICKER_BIST100,
        "usdtry_ticker": TICKER_USDTRY,
        "risksiz_faiz_yillik": rf_annual,
        "aciklama": "Sharpe/Sortino: gunluk fazla getiri / risk; Alpha: CAPM (BIST100); MaxDD: fiyat serisi.",
    }
    if skip or not _HAS_ANALYTICS:
        for e in entries:
            e["stats"] = {p: _empty_stat_block() for p in STAT_PERIODS}
        meta["durum"] = "istatistik_atlandi"
        return meta

    fund_map: Dict[str, Any] = {}
    min_ts: Optional[pd.Timestamp] = None
    max_ts: Optional[pd.Timestamp] = None

    for e in entries:
        kod = e.get("kod") or ""
        path = data_dir / f"{kod}_tefas.json"
        if not path.is_file():
            e["stats"] = {p: _empty_stat_block() for p in STAT_PERIODS}
            continue
        try:
            with open(path, "r", encoding="utf-8") as fp:
                bundle = json.load(fp)
        except (OSError, ValueError):
            e["stats"] = {p: _empty_stat_block() for p in STAT_PERIODS}
            continue
        ser = _rows_to_close_series(bundle.get("veri") or [])
        fund_map[kod] = ser
        if ser is not None and len(ser) > 0:
            mn, mx = ser.index.min(), ser.index.max()
            min_ts = mn if min_ts is None else min(min_ts, mn)
            max_ts = mx if max_ts is None else max(max_ts, mx)

    if min_ts is None or max_ts is None:
        for e in entries:
            if "stats" not in e:
                e["stats"] = {p: _empty_stat_block() for p in STAT_PERIODS}
        meta["durum"] = "fon_serisi_yok"
        return meta

    xu, usd, err = download_benchmark_series(
        datetime.combine(min_ts.date(), datetime.min.time()),
        datetime.combine(max_ts.date(), datetime.min.time()),
    )
    meta["indirme_hatasi"] = err
    if xu is None or len(xu) < MIN_OBS_METRICS:
        for e in entries:
            e["stats"] = {p: _empty_stat_block() for p in STAT_PERIODS}
        meta["durum"] = "benchmark_yok"
        return meta

    if usd is not None and len(usd) > 0:
        meta["usdtry_son"] = float(usd.iloc[-1])
        meta["usdtry_tarih"] = str(usd.index[-1].date())
    meta["xu100_son"] = float(xu.iloc[-1])
    meta["xu100_tarih"] = str(xu.index[-1].date())
    meta["durum"] = "tamam"

    for e in entries:
        kod = e.get("kod") or ""
        ser = fund_map.get(kod)
        if ser is None or len(ser) < MIN_OBS_METRICS:
            e["stats"] = {p: _empty_stat_block() for p in STAT_PERIODS}
            continue
        e["stats"] = build_fund_stats_map(ser, xu, rf_annual)

    return meta


def save_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def write_manifest(
    data_dir: Path,
    entries: List[Dict[str, Any]],
    hedef_gun: int,
    benchmarks_meta: Optional[Dict[str, Any]] = None,
) -> None:
    manifest = {
        "guncelleme": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "hedef_gun": hedef_gun,
        "kategori": "Hisse Senedi Yoğun Fon",
        "beklenen_min_gun": EXPECTED_SPAN_DAYS,
        "benchmarks": benchmarks_meta or {},
        "fonlar": entries,
    }
    save_json(data_dir / "manifest.json", manifest)


def manifest_entry_from_bundle(rel_path: str, bundle: Dict[str, Any]) -> Dict[str, Any]:
    kod = bundle.get("fon_kodu") or ""
    return {
        "kod": kod,
        "ad": bundle.get("fon_unvan") or kod,
        "durum": bundle.get("durum_panel") or "veri_eksik",
        "neden": bundle.get("neden"),
        "kayit": bundle.get("kayit_sayisi", 0),
        "gun_kapsami": bundle.get("gun_kapsami", 0),
        "dosya": rel_path.replace("\\", "/"),
    }


def refresh_manifest_from_disk(
    data_dir: Path,
    hedef_gun: int,
    rf_annual: float = RISKSIZ_YILLIK_DEFAULT,
    skip_stats: bool = False,
) -> None:
    entries: List[Dict[str, Any]] = []
    for path in sorted(data_dir.glob("*_tefas.json")):
        if path.name == "manifest.json":
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                bundle = json.load(f)
        except (OSError, ValueError):
            continue
        rel = f"{data_dir.as_posix().rstrip('/')}/{path.name}"
        if not rel.startswith("data/"):
            rel = f"data/{path.name}"
        entries.append(manifest_entry_from_bundle(rel, bundle))
    entries.sort(key=lambda x: x["kod"])
    bench = enrich_manifest_entries_with_stats(entries, data_dir, rf_annual, skip_stats)
    write_manifest(data_dir, entries, hedef_gun, bench)


def run_single_fund(
    fon: str,
    gun: int,
    data_dir: Path,
    fontip: str = "YAT",
    delay: float = 0.32,
    rf_annual: float = RISKSIZ_YILLIK_DEFAULT,
    skip_stats: bool = False,
) -> int:
    session = _make_session()
    base, ref = resolve_history_base(session)
    end = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=max(1, gun))
    rows = fetch_fund_history(session, base, ref, fon, start, end, fontip, delay)
    unvan = fon
    if rows:
        last = rows[-1]
        unvan = (last.get("FONUNVAN") or last.get("fonunvan") or fon).strip() or fon
    bundle = build_bundle(fon, unvan, start, end, base, rows, fontip)
    out = data_dir / f"{fon.upper()}_tefas.json"
    save_json(out, bundle)
    refresh_manifest_from_disk(data_dir, gun, rf_annual, skip_stats)
    print(f"OK {fon}: {len(rows)} kayit -> {out} ({bundle['durum_panel']})")
    return 0


def run_full_hsyf(
    gun: int,
    data_dir: Path,
    fontip: str = "YAT",
    delay: float = 0.32,
    max_fon: Optional[int] = None,
    rf_annual: float = RISKSIZ_YILLIK_DEFAULT,
    skip_stats: bool = False,
) -> int:
    session = _make_session()
    funds = discover_hsyf_funds(session)
    if not funds:
        print("HSYF listesi alinamadi (tefas.gov.tr). Daha sonra tekrar deneyin.", file=sys.stderr)
        return 1
    if max_fon is not None:
        funds = funds[: max_fon]
    print(f"HSYF fon sayisi: {len(funds)}")

    base, ref = resolve_history_base(session)
    print(f"Tarihsel API tabani: {base}")

    end = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=max(1, gun))

    entries: List[Dict[str, Any]] = []
    for i, item in enumerate(funds, 1):
        kod = item["fon_kodu"]
        unvan = item["fon_unvan"]
        print(f"[{i}/{len(funds)}] {kod} ...", flush=True)
        try:
            rows = fetch_fund_history(session, base, ref, kod, start, end, fontip, delay)
        except Exception as exc:
            print(f"  ! hata: {exc}", flush=True)
            rows = []
        if rows:
            u = (rows[-1].get("FONUNVAN") or unvan).strip() or unvan
        else:
            u = unvan
        bundle = build_bundle(kod, u, start, end, base, rows, fontip)
        out = data_dir / f"{kod}_tefas.json"
        save_json(out, bundle)
        entries.append(manifest_entry_from_bundle(f"data/{kod}_tefas.json", bundle))

    bench = enrich_manifest_entries_with_stats(entries, data_dir, rf_annual, skip_stats)
    write_manifest(data_dir, entries, gun, bench)
    tam = sum(1 for e in entries if e["durum"] == "tam")
    eksik = len(entries) - tam
    print(f"Bitti. tam={tam}, veri_eksik={eksik}, manifest=data/manifest.json")
    return 0


def main() -> int:
    _ensure_utf8_stdio()
    p = argparse.ArgumentParser(description="TEFAS HSYF kesif ve tarihsel veri.")
    p.add_argument(
        "fon",
        nargs="?",
        default=None,
        help="Tek fon kodu (ornegin MAC). Verilmezse tum HSYF taranir.",
    )
    p.add_argument("--gun", type=int, default=DEFAULT_GUN, help=f"Geri gidilecek gun (varsayilan {DEFAULT_GUN})")
    p.add_argument(
        "--veri-klasoru",
        default="data",
        help="Cikti klasoru (varsayilan data/)",
    )
    p.add_argument("--liste", action="store_true", help="Sadece HSYF kodlarini listele ve cik")
    p.add_argument(
        "--manifest-yenile",
        action="store_true",
        help="data/*_tefas.json dosyalarindan manifest.json uret",
    )
    p.add_argument("--max-fon", type=int, default=None, help="Test: ilk N fonla sinirla")
    p.add_argument("--gecikme", type=float, default=0.32, help="Parcalar arasi bekleme saniye")
    p.add_argument(
        "--fontip",
        default="YAT",
        choices=("YAT", "EMK", "BYF"),
        help="Menkul turu",
    )
    p.add_argument(
        "--risksiz-faiz",
        type=float,
        default=RISKSIZ_YILLIK_DEFAULT,
        help=f"Yillik risksiz oran (Sharpe/Sortino/CAPM icin, varsayilan {RISKSIZ_YILLIK_DEFAULT})",
    )
    p.add_argument(
        "--istatistik-atlama",
        action="store_true",
        help="yfinance / benchmark ve stats hesaplamasini atla",
    )
    args = p.parse_args()

    data_dir = Path(args.veri_klasoru)
    data_dir.mkdir(parents=True, exist_ok=True)

    if args.manifest_yenile:
        refresh_manifest_from_disk(
            data_dir,
            args.gun,
            args.risksiz_faiz,
            args.istatistik_atlama,
        )
        print(f"manifest guncellendi: {data_dir / 'manifest.json'}")
        return 0

    session = _make_session()
    if args.liste:
        funds = discover_hsyf_funds(session)
        for f in funds:
            print(f"{f['fon_kodu']}\t{f['fon_unvan']}")
        print(f"Toplam: {len(funds)}")
        return 0

    if args.fon:
        return run_single_fund(
            args.fon.strip().upper(),
            args.gun,
            data_dir,
            fontip=args.fontip,
            delay=args.gecikme,
            rf_annual=args.risksiz_faiz,
            skip_stats=args.istatistik_atlama,
        )

    return run_full_hsyf(
        args.gun,
        data_dir,
        fontip=args.fontip,
        delay=args.gecikme,
        max_fon=args.max_fon,
        rf_annual=args.risksiz_faiz,
        skip_stats=args.istatistik_atlama,
    )


if __name__ == "__main__":
    raise SystemExit(main())
