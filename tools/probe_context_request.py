"""Browser context.request ile (page render olmadan) detail HTML alabiliyor muyuz?"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tefas_browser_client import TefasBrowserClient

with TefasBrowserClient(headless=True) as cli:
    page = cli._page
    ctx = cli._context
    for kod in ["MAC", "AAV", "ACR"]:
        url = f"https://www.tefas.gov.tr/tr/fon-detayli-analiz/{kod}"
        try:
            r = ctx.request.get(url, timeout=20000)
            txt = r.text()
            print(f"{kod}: status={r.status} len={len(txt)} kapLink={txt.count('kapLink')} fonKategori={txt.count('fonKategori')}")
        except Exception as e:
            print(f"{kod}: error {e}")
