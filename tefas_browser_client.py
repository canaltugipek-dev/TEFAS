#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TEFAS yeni Next.js API'sine stealth Chromium uzerinden erisim.

2026 Nisan'da TEFAS:
  - Eski .aspx sayfalari ve /api/DB/* endpointleri 404 ("Method not found or disabled!")
  - F5 BIG-IP TSPD anti-bot koruma katmani aktif
  - Yeni UI Next.js tabanli; rotalar /tr/fund-detail/<KOD>, /tr/fon-getirileri vs.
  - Yeni JSON API'leri:
      POST /api/funds/fonFiyatBilgiGetir   {fonKodu, dil, periyod}
      POST /api/funds/fonBilgiGetir        {fonKodu, dil}
      POST /api/funds/fonGetiriBazliBilgiGetir
      POST /api/statistics/tefas/getFplFonList

Bu modul tek bir Chromium oturumu acar (stealth + warmup), sayfa icinden
fetch ile yeni API'yi cagirir. Boylece TSPD cookie'leri otomatik kullanilir.
"""
from __future__ import annotations

import json as _json
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Playwright agir bagimliliklar; modul yuklendiginde import etmeyelim,
# ihtiyac aninda yukleyelim ki test/ozet komutlari hizli kalsin.
_PW = None  # placeholder

WARMUP_URL = "https://www.tefas.gov.tr/tr/fund-detail/MAC"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
BASE_URL = "https://www.tefas.gov.tr"


class TefasBrowserClient:
    """Stealth Chromium oturumu uzerinden TEFAS yeni API'sine eriler."""

    def __init__(self, headless: bool = True, warmup_url: str = WARMUP_URL):
        self._headless = headless
        self._warmup_url = warmup_url
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._lock = threading.Lock()

    def __enter__(self) -> "TefasBrowserClient":
        self.start()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def start(self) -> None:
        with self._lock:
            if self._page is not None:
                return
            from playwright.sync_api import sync_playwright
            from playwright_stealth import stealth_sync

            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(
                headless=self._headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            self._context = self._browser.new_context(
                user_agent=USER_AGENT,
                locale="tr-TR",
                viewport={"width": 1366, "height": 800},
                extra_http_headers={"Accept-Language": "tr-TR,tr;q=0.9"},
            )
            self._page = self._context.new_page()
            stealth_sync(self._page)
            self._warmup()

    def _warmup(self) -> None:
        assert self._page is not None
        self._page.goto(self._warmup_url, wait_until="domcontentloaded", timeout=60000)
        try:
            self._page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        self._page.wait_for_timeout(1500)

    def close(self) -> None:
        with self._lock:
            for closer in (
                lambda: self._context and self._context.close(),
                lambda: self._browser and self._browser.close(),
                lambda: self._pw and self._pw.stop(),
            ):
                try:
                    closer()
                except Exception:
                    pass
            self._page = None
            self._context = None
            self._browser = None
            self._pw = None

    def _post_json(
        self,
        path: str,
        body: Dict[str, Any],
        retries: int = 3,
        backoff: float = 1.5,
    ) -> Any:
        """Sayfa icinden POST + JSON parse."""
        if self._page is None:
            self.start()
        assert self._page is not None
        url = BASE_URL + path
        js = """
        async ([url, body]) => {
          const res = await fetch(url, {
            method: 'POST',
            credentials: 'include',
            headers: {
              'Content-Type': 'application/json',
              'Accept': 'application/json',
            },
            body: JSON.stringify(body),
          });
          const txt = await res.text();
          return { status: res.status, body: txt };
        }
        """
        last_err: Optional[Exception] = None
        for attempt in range(max(1, retries)):
            try:
                with self._lock:
                    res = self._page.evaluate(js, [url, body])
            except Exception as exc:
                last_err = exc
                time.sleep(backoff * (attempt + 1))
                # restart browser if context died
                if "context" in str(exc).lower() or "closed" in str(exc).lower():
                    try:
                        self.close()
                    except Exception:
                        pass
                    self.start()
                continue
            status = res.get("status")
            txt = res.get("body") or ""
            if status != 200:
                last_err = RuntimeError(
                    f"{path} status={status} body={txt[:200]!r}"
                )
                # transient WAF or session expiry: re-warmup
                if status in (401, 403, 419, 429) or "Request Rejected" in txt:
                    try:
                        self._warmup()
                    except Exception:
                        pass
                time.sleep(backoff * (attempt + 1))
                continue
            try:
                return _json.loads(txt)
            except ValueError as exc:
                last_err = exc
                time.sleep(backoff * (attempt + 1))
                continue
        raise RuntimeError(f"TEFAS POST basarisiz: {path} body={body!r}: {last_err}")

    # --- API metodlari ---------------------------------------------------

    def get_fund_list(self) -> List[Dict[str, Any]]:
        """getFplFonList: tum fonlarin temel kayitlari (fonKod/unvan/kurucu vs)."""
        data = self._post_json("/api/statistics/tefas/getFplFonList", {})
        return list(data.get("data") or [])

    def get_fund_info(self, fon_kodu: str) -> Optional[Dict[str, Any]]:
        """fonBilgiGetir: tek fonun ozet bilgisi (sonFiyat, payAdet, vs)."""
        data = self._post_json(
            "/api/funds/fonBilgiGetir", {"fonKodu": fon_kodu, "dil": "TR"}
        )
        rl = data.get("resultList") or []
        return rl[0] if rl else None

    def get_price_history(
        self, fon_kodu: str, periyod: int = 60
    ) -> List[Dict[str, Any]]:
        """fonFiyatBilgiGetir: tarihsel fiyat listesi.

        periyod: ay sayisi. Desteklenen degerler: 1, 3, 6, 12, 36, 60.
        """
        data = self._post_json(
            "/api/funds/fonFiyatBilgiGetir",
            {"fonKodu": fon_kodu, "dil": "TR", "periyod": periyod},
        )
        return list(data.get("resultList") or [])

    def get_fund_detail_html(self, fon_kodu: str, timeout_ms: int = 45000) -> str:
        """Fon detayli analiz sayfasinin HTML'ini getirir (RSC payload icerir).

        TSPD anti-bot'u page.goto uzerinden gecmek gerektiginden context.request
        yerine sayfayi gercek goto ile aciyoruz. Render beklemeyiz; HTML zaten
        SSR ile dolu gelir.
        """
        if self._page is None:
            self.start()
        assert self._page is not None
        url = f"{BASE_URL}/tr/fon-detayli-analiz/{fon_kodu.strip().upper()}"
        with self._lock:
            try:
                self._page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            except Exception:
                pass
            try:
                return self._page.content()
            except Exception:
                return ""

    def get_fund_kap_info(self, fon_kodu: str, retries: int = 2) -> Optional[Dict[str, Any]]:
        """Fon detay HTML'inden RSC profilData/bilgiData JSON'unu parse eder.

        Dondurur: dict (kapLink, fonUnvan, fonKategori, fonKodu, sonFiyat, ...).
        Basarisizsa warmup + 1 retry yapar.
        """
        kod = fon_kodu.strip().upper()
        for attempt in range(max(1, retries)):
            html = self.get_fund_detail_html(kod)
            if html:
                info = parse_fund_detail_html(html, kod)
                if info and info.get("kapLink"):
                    return info
            if attempt + 1 < retries:
                # oturum yipranmis olabilir: kisa bekle + warmup
                try:
                    if self._page is not None:
                        self._page.wait_for_timeout(2000)
                    self._warmup()
                except Exception:
                    pass
        # Son deneme: kismi bilgiyi de dondur
        html = self.get_fund_detail_html(kod)
        return parse_fund_detail_html(html, kod) if html else None

    def restart(self) -> None:
        """Browser context'ini kapat ve yeniden ac (uzun batch islerde periyodik refresh)."""
        try:
            self.close()
        except Exception:
            pass
        self.start()

    def get_fund_universe_with_returns(
        self, fontip: str = "YAT", islem: int = 1
    ) -> List[Dict[str, Any]]:
        """fonGetiriBazliBilgiGetir: tum fon universinin fonTurAciklama+getiri ozeti."""
        body = {
            "dil": "TR",
            "fonTipi": fontip,
            "kurucuKodu": None,
            "sfonTurKod": None,
            "fonTurAciklama": None,
            "islem": islem,
            "fonTurKod": None,
            "fonGrupKod": None,
            "fonKodu": None,
        }
        data = self._post_json("/api/funds/fonGetiriBazliBilgiGetir", body)
        return list(data.get("resultList") or [])


# --- Modul-seviyesinde paylasilan singleton ----------------------------------

_GLOBAL_CLIENT_LOCK = threading.Lock()
_GLOBAL_CLIENT: Optional[TefasBrowserClient] = None


def get_browser_client() -> TefasBrowserClient:
    global _GLOBAL_CLIENT
    with _GLOBAL_CLIENT_LOCK:
        if _GLOBAL_CLIENT is None:
            _GLOBAL_CLIENT = TefasBrowserClient(headless=True)
            _GLOBAL_CLIENT.start()
        return _GLOBAL_CLIENT


def close_browser_client() -> None:
    global _GLOBAL_CLIENT
    with _GLOBAL_CLIENT_LOCK:
        if _GLOBAL_CLIENT is not None:
            try:
                _GLOBAL_CLIENT.close()
            finally:
                _GLOBAL_CLIENT = None


# --- Eski JSON formatina donusum ---------------------------------------------

LEGACY_PRICE_KEYS = ("TARIH", "FONKODU", "FONUNVAN", "FIYAT")


def period_for_days(days: int) -> int:
    """Gun sayisini fonFiyatBilgiGetir.periyod (ay) degerine indirger."""
    if days <= 30:
        return 1
    if days <= 90:
        return 3
    if days <= 180:
        return 6
    if days <= 365:
        return 12
    if days <= 1095:
        return 36
    return 60


_RSC_CHUNK_RE = re.compile(
    r"self\.__next_f\.push\(\[\s*\d+\s*,\s*\"((?:\\.|[^\"\\])*)\"\s*\]\s*\)"
)


def _decode_rsc_chunks(html: str) -> str:
    """Sayfadaki self.__next_f.push([N,'...']) parcalarini birlestirip decode eder."""
    pieces: List[str] = []
    for m in _RSC_CHUNK_RE.finditer(html):
        raw = m.group(1)
        try:
            decoded = bytes(raw, "utf-8").decode("unicode_escape")
        except Exception:
            decoded = raw
        # unicode_escape Latin-1 olarak yorumlanir; Turkce icin tekrar dogrula
        try:
            decoded_b = decoded.encode("latin-1", errors="ignore")
            decoded2 = decoded_b.decode("utf-8", errors="ignore")
            if decoded2:
                decoded = decoded2
        except Exception:
            pass
        pieces.append(decoded)
    return "\n".join(pieces)


def _extract_balanced_json(text: str, start: int) -> Optional[str]:
    """text[start] '{' karakteri olmali. Eslesmis kapatma parantezine kadar JSON dondurur."""
    if start < 0 or start >= len(text) or text[start] != "{":
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    return None


def _find_json_object_with_key(text: str, key: str) -> Optional[Dict[str, Any]]:
    """text icinde "key":{...} araminin etrafini saran en iyi JSON objesini bulur."""
    needle = f'"{key}":{{'
    pos = 0
    while True:
        i = text.find(needle, pos)
        if i < 0:
            return None
        brace_start = i + len(needle) - 1
        raw = _extract_balanced_json(text, brace_start)
        if raw:
            try:
                return _json.loads(raw)
            except ValueError:
                pass
        pos = i + 1


def parse_fund_detail_html(html: str, fon_kodu: str) -> Optional[Dict[str, Any]]:
    """Detay sayfasindan profilData + bilgiData ve kapLink ayiklar.

    Return dict:
      {
        "fonKodu": str,
        "fonUnvan": str,
        "kapLink": Optional[str],
        "fonKategori": Optional[str],
        "fonTipi": Optional[str],
        "riskDegeri": Optional[str],
        "isinKodu": Optional[str],
        "sonFiyat": Optional[float],
        "portBuyukluk": Optional[float],
        "yatirimciSayi": Optional[int],
        "pazarPayi": Optional[float],
      }
    """
    decoded = _decode_rsc_chunks(html) or html
    profil = _find_json_object_with_key(decoded, "profilData")
    bilgi = _find_json_object_with_key(decoded, "bilgiData")
    if not profil and not bilgi:
        # Fallback: HTML'den direkt kapLink yakala
        m = re.search(r'"kapLink"\s*:\s*"([^"]+)"', decoded)
        if not m:
            return None
        return {"fonKodu": fon_kodu.upper(), "kapLink": m.group(1)}
    out: Dict[str, Any] = {"fonKodu": fon_kodu.upper()}
    if profil:
        for k in (
            "fonKodu",
            "fonUnvan",
            "kapLink",
            "isinKodu",
            "riskDegeri",
            "tefasDurum",
            "minAlis",
            "minSatis",
            "girisKomisyonu",
            "cikisKomisyonu",
            "fonSatisValor",
            "fonGeriAlisValor",
            "faizIcerigi",
        ):
            if k in profil:
                out[k] = profil[k]
    if bilgi:
        for k in (
            "fonUnvan",
            "sonFiyat",
            "gunlukGetiri",
            "payAdet",
            "portBuyukluk",
            "fonKategori",
            "kategoriDerece",
            "kategoriFonSay",
            "yatirimciSayi",
            "pazarPayi",
        ):
            if k in bilgi:
                out.setdefault(k, bilgi[k]) if k == "fonUnvan" else out.update({k: bilgi[k]})
    # fonTipi RSC'de bazen ayri alan olarak veriliyor
    m = re.search(r'"fonTipi"\s*:\s*"([A-Za-z])"', decoded)
    if m:
        out["fonTipi"] = m.group(1)
    return out


def browser_rows_to_legacy(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """fonFiyatBilgiGetir.resultList -> eski TEFAS history row formatina."""
    out: List[Dict[str, Any]] = []
    for it in items:
        tarih = it.get("tarih")
        if not tarih:
            continue
        try:
            dt = datetime.strptime(tarih, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        epoch_ms = int(dt.timestamp() * 1000)
        try:
            fiyat = float(it.get("fiyat"))
        except (TypeError, ValueError):
            continue
        out.append(
            {
                "TARIH": str(epoch_ms),
                "FONKODU": (it.get("fonKodu") or "").strip().upper(),
                "FONUNVAN": (it.get("fonUnvan") or "").strip(),
                "FIYAT": fiyat,
                "TEDPAYSAYISI": None,
                "KISISAYISI": None,
                "PORTFOYBUYUKLUK": None,
                "BilFiyat": "-",
            }
        )
    return out
