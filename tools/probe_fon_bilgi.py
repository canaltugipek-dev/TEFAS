"""Inspect full fonBilgiGetir response to find KAP link / asset distribution."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tefas_browser_client import TefasBrowserClient

with TefasBrowserClient(headless=True) as c:
    info = c.get_fund_info("MAC")
    print("keys:", list(info.keys()) if info else None)
    print(json.dumps(info, ensure_ascii=False, indent=2)[:3000])
