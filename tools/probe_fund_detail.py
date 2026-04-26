"""Fon detay sayfasinin tum API cagrilarini ve tam yanitlarini yakala."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync

OUT = Path(__file__).resolve().parent / "probe_detail_out"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> None:
    api_responses: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="tr-TR",
            viewport={"width": 1366, "height": 800},
            extra_http_headers={"Accept-Language": "tr-TR,tr;q=0.9"},
        )
        page = ctx.new_page()
        stealth_sync(page)

        def on_response(res):
            try:
                if "/api/" not in res.url:
                    return
                body = ""
                ct = res.headers.get("content-type") or ""
                if "json" in ct:
                    try:
                        body = res.text()
                    except Exception:
                        body = ""
                api_responses.append(
                    {
                        "url": res.url,
                        "method": res.request.method,
                        "post": res.request.post_data,
                        "status": res.status,
                        "ct": ct,
                        "body": body[:6000],
                    }
                )
            except Exception:
                pass

        page.on("response", on_response)

        for url in [
            "https://www.tefas.gov.tr/tr/fund-detail/MAC",
            "https://www.tefas.gov.tr/tr/fon-detayli-analiz/MAC",
        ]:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_load_state("networkidle", timeout=25000)
            except Exception:
                pass
            page.wait_for_timeout(4000)
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            except Exception:
                pass
            page.wait_for_timeout(3000)
            try:
                page.evaluate("window.scrollTo(0, 0)")
            except Exception:
                pass
            page.wait_for_timeout(2000)

        # try clicking known UI elements that might trigger more API calls (asset distribution / PDR)
        for sel in [
            'button:has-text("Portföy Dağılımı")',
            'button:has-text("Varlık Dağılımı")',
            'button:has-text("Detaylı Analiz")',
            'a:has-text("KAP")',
            'a:has-text("Portföy Dağılım Raporu")',
        ]:
            try:
                page.click(sel, timeout=2000)
                page.wait_for_timeout(2000)
            except Exception:
                pass

        # Print summary table
        seen = {}
        for r in api_responses:
            key = (r.get("method"), r.get("url", "").split("?")[0])
            if key not in seen:
                seen[key] = r
        print("Unique API endpoints touched:")
        for (m, u), r in sorted(seen.items()):
            print(f"\n  {m} {u}")
            print(f"    status={r.get('status')} ct={r.get('ct')}")
            if r.get("post"):
                print(f"    post: {(r['post'] or '')[:200]}")
            body = r.get("body") or ""
            print(f"    body[:500]: {body[:500]!r}")

        (OUT / "fund_detail_api.json").write_text(
            json.dumps(api_responses, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        browser.close()


if __name__ == "__main__":
    main()
