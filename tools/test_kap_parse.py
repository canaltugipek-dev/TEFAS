"""tefas_browser_client.get_fund_kap_info parse testi."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tefas_browser_client import TefasBrowserClient

with TefasBrowserClient(headless=True) as cli:
    for kod in ["MAC", "AAV", "ACR", "ATI"]:
        info = cli.get_fund_kap_info(kod)
        print(f"\n=== {kod} ===")
        print(json.dumps(info, ensure_ascii=False, indent=2))
