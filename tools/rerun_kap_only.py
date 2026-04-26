"""Sadece KAP isteklerini yeniden dener; mevcut JSON'daki kap_link/unvan/varlik_dagilimi'ni reuse eder.

Playwright/TEFAS fetch yok. Cok daha hizli ve sadece KAP rate-limit sorununu hedefler.
fon_hisse_scraper.py'deki retry+backoff sayesinde 429/503 durumlarinda otomatik bekler.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fon_hisse_scraper import (  # noqa: E402
    OUT_PATH,
    _ozet_satir,
    _print_ozet_tablo,
    _session,
    _write_per_fund_json,
    fetch_real_hisse_rows,
    merge_one,
)

DELAY_S = 1.5


def block_to_tefas_payload(block: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Mevcut JSON block'undan fetch_real_hisse_rows'un bekledigi tefas_payload'i kur."""
    kap_link = block.get("kap_link")
    if not kap_link:
        return None
    unvan = block.get("unvan") or ""
    fp = {"KAPLINK": kap_link, "FONUNVAN": unvan}
    fi = {"FONUNVAN": unvan}
    alloc: List[Dict[str, Any]] = []
    for row in block.get("varlik_dagilimi") or []:
        tip = row.get("tip") or row.get("KIYMETTIP")
        oran = row.get("oran")
        if oran is None:
            oran = row.get("PORTFOYORANI")
        alloc.append({"KIYMETTIP": tip, "PORTFOYORANI": oran})
    return {
        "fundProfile": [fp],
        "fundInfo": [fi],
        "fundAllocation": alloc,
        "fundCategory": None,
    }


def main() -> int:
    if not OUT_PATH.is_file():
        print("fon_hisse_birlesik.json yok, once full run yapin.", file=sys.stderr)
        return 1
    data = json.loads(OUT_PATH.read_text(encoding="utf-8"))
    fonlar = data.get("fonlar") or {}
    failed_codes = sorted(
        kod
        for kod, v in fonlar.items()
        if (v.get("hisse_durumu") or "bulunamadi") != "ok"
    )
    print(f"Toplam fon: {len(fonlar)}, basarisizlar: {len(failed_codes)}", flush=True)
    if not failed_codes:
        print("Hicbir basarisiz yok, cikis.")
        return 0

    sess = _session()
    ozet: List[Dict[str, Any]] = []
    yeni_ok = 0
    for i, kod in enumerate(failed_codes):
        if i and DELAY_S:
            time.sleep(DELAY_S)
        block_old = fonlar.get(kod) or {}
        tefas = block_to_tefas_payload(block_old)
        if not tefas:
            print(f"[{i+1:3}/{len(failed_codes)}] {kod}: kap_link yok, atlaniyor", flush=True)
            ozet.append(_ozet_satir(kod, block_old))
            continue
        hisse_result = fetch_real_hisse_rows(sess, kod, tefas, log=False)
        block_new = merge_one(kod, tefas, hisse_result)
        # 'kaynak_tefas' isareti orijinaldeki gibi kalsin
        if "kaynak_tefas" in block_old:
            block_new["kaynak_tefas"] = block_old["kaynak_tefas"]
        old_durum = block_old.get("hisse_durumu") or "bulunamadi"
        new_durum = block_new.get("hisse_durumu") or "bulunamadi"
        # Sadece yeni durum daha iyi ise (ok'a gectiyse) kaydet
        if new_durum == "ok" and old_durum != "ok":
            fonlar[kod] = block_new
            _write_per_fund_json(kod, block_new)
            yeni_ok += 1
            n = len(block_new.get("hisseler") or [])
            print(f"[{i+1:3}/{len(failed_codes)}] {kod}: OK (+{n} hisse)", flush=True)
        else:
            # ok'a gecemediyse mesaji guncelleyip eskiyi koru (debug icin)
            block_old["hisse_mesaj"] = block_new.get("hisse_mesaj") or block_old.get("hisse_mesaj")
            fonlar[kod] = block_old
            print(
                f"[{i+1:3}/{len(failed_codes)}] {kod}: {new_durum} - {block_new.get('hisse_mesaj')}",
                flush=True,
            )
        ozet.append(_ozet_satir(kod, fonlar[kod]))

    data["fonlar"] = fonlar
    data["guncelleme"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    OUT_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nYazildi: {OUT_PATH}", flush=True)
    _print_ozet_tablo(ozet)

    ok_total = sum(1 for v in fonlar.values() if (v.get("hisse_durumu") or "") == "ok")
    print(
        f"\nGENEL: toplam={len(fonlar)} OK={ok_total} (+{yeni_ok} yeni) hata/uygun_degil={len(fonlar) - ok_total}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
