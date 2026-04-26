"""5 fonla rerun_kap_only.py'nin calisip calismadigini test eder.
Cikti yapmaz, sadece ekranda gosterir, JSON yazmaz.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fon_hisse_scraper import OUT_PATH, _session, fetch_real_hisse_rows  # noqa: E402
from tools.rerun_kap_only import block_to_tefas_payload  # noqa: E402

CODES = ["ACC", "BDS", "ASJ", "ADP", "FPH"]


def main() -> int:
    data = json.loads(OUT_PATH.read_text(encoding="utf-8"))
    fonlar = data.get("fonlar") or {}
    sess = _session()
    for kod in CODES:
        block = fonlar.get(kod) or {}
        tefas = block_to_tefas_payload(block)
        if not tefas:
            print(f"{kod}: kap_link yok"); continue
        t0 = time.time()
        result = fetch_real_hisse_rows(sess, kod, tefas, log=False)
        dt = time.time() - t0
        n = len(result.get("hisseler") or [])
        print(
            f"{kod:5} {result['hisse_durumu']:13} #{n:3} mesaj={result.get('hisse_mesaj')!s:.60} ({dt:.1f}s)"
        )
        time.sleep(1.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
