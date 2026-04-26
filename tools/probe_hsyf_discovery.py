"""Test HSYF discovery via fonGetiriBazliBilgiGetir."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tefas_browser_client import TefasBrowserClient

with TefasBrowserClient(headless=True) as c:
    rows = c.get_fund_universe_with_returns(fontip="YAT", islem=1)
    print("rows:", len(rows))
    if rows:
        print("first keys:", list(rows[0].keys()))
        print("first:", rows[0])
        # Fon turlerini sayalim
        from collections import Counter
        types = Counter(r.get("fonTurAciklama") for r in rows)
        print("\nfonTurAciklama dagilimi:")
        for t, n in types.most_common():
            print(f"  {n:4d}  {t}")
        # HSYF: turde 'Hisse Senedi' + unvanda 'Yogun' / 'YOGUN' / 'EQUITY-INTENSIVE'
        hsyf = [
            r for r in rows
            if "hisse senedi" in (r.get("fonTurAciklama") or "").lower()
            and (
                "yoğun" in (r.get("fonUnvan") or "").lower()
                or "yogun" in (r.get("fonUnvan") or "").lower()
                or "equity-intensive" in (r.get("fonUnvan") or "").lower()
            )
        ]
        print("\nHSYF count by filter:", len(hsyf))
        for r in hsyf[:5]:
            print("  ", r.get("fonKodu"), "|", r.get("fonUnvan"), "|", r.get("fonTurAciklama"))
