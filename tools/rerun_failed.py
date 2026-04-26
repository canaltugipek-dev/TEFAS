"""Mevcut fon_hisse_birlesik.json'da OK olmayan fonlari tekrar tara.
Mevcut OK kayitlarini koruyarak basarisizlari yeniden dener.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fon_hisse_scraper import (  # noqa: E402
    DATA,
    OUT_PATH,
    _ozet_satir,
    _print_ozet_tablo,
    _session,
    _write_per_fund_json,
    fetch_real_hisse_rows,
    fetch_tefas_analyze,
    merge_one,
)
from tefas_browser_client import close_browser_client, get_browser_client  # noqa: E402

BROWSER_REFRESH_EVERY = 25
DELAY_S = 1.5


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
    print(f"Toplam fon: {len(fonlar)}, basarisizlar: {len(failed_codes)}")
    if not failed_codes:
        print("Hicbir basarisiz yok, cikis.")
        return 0

    sess = _session()
    client = get_browser_client()
    ozet = []
    try:
        for i, kod in enumerate(failed_codes):
            if i and DELAY_S:
                time.sleep(DELAY_S)
            if i and i % BROWSER_REFRESH_EVERY == 0:
                try:
                    print(f"[BROWSER] {i} fondan sonra yenileniyor...", flush=True)
                    client.restart()
                except Exception as e:
                    print(f"[BROWSER] yenileme hatasi: {e}", flush=True)
            tefas = fetch_tefas_analyze(client, kod)
            hisse_result = fetch_real_hisse_rows(sess, kod, tefas, log=True)
            block = merge_one(kod, tefas, hisse_result)
            fonlar[kod] = block
            _write_per_fund_json(kod, block)
            ozet.append(_ozet_satir(kod, block))
    finally:
        try:
            close_browser_client()
        except Exception:
            pass

    data["fonlar"] = fonlar
    data["guncelleme"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    OUT_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Yazildi: {OUT_PATH}")
    _print_ozet_tablo(ozet)

    # Genel ozet
    ok = sum(1 for v in fonlar.values() if (v.get("hisse_durumu") or "") == "ok")
    print(
        f"\nGENEL: toplam={len(fonlar)} OK={ok} hata/uygun_degil={len(fonlar) - ok}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
