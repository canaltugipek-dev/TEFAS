"""Fon detay sayfasini ic ic gez, tab'lara tikla, tum API cagrilarini topla.

Hedef: KAP linki ve varlik dagilimi (fundAllocation) endpoint'ini bulmak.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync

OUT = Path(__file__).resolve().parent / "probe_detail2_out"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> None:
    api_calls: list[dict] = []
    page_html_dump: dict[str, str] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="tr-TR",
            viewport={"width": 1366, "height": 900},
            extra_http_headers={"Accept-Language": "tr-TR,tr;q=0.9"},
        )
        page = ctx.new_page()
        stealth_sync(page)

        def on_response(res):
            try:
                if "/api/" not in res.url:
                    return
                ct = res.headers.get("content-type") or ""
                body = ""
                if "json" in ct:
                    try:
                        body = res.text()
                    except Exception:
                        body = ""
                api_calls.append(
                    {
                        "url": res.url,
                        "method": res.request.method,
                        "post": res.request.post_data,
                        "status": res.status,
                        "body_preview": body[:1500],
                        "body_len": len(body),
                    }
                )
            except Exception:
                pass

        page.on("response", on_response)

        target_pages = [
            "https://www.tefas.gov.tr/tr/fon-detayli-analiz/MAC",
            "https://www.tefas.gov.tr/tr/fund-detail/MAC",
        ]
        for url in target_pages:
            api_calls.append({"_navigate": url})
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                print(f"goto failed: {url}: {e}")
                continue
            try:
                page.wait_for_load_state("networkidle", timeout=30000)
            except Exception:
                pass
            page.wait_for_timeout(4000)
            for _ in range(6):
                try:
                    page.evaluate("window.scrollBy(0, 500)")
                except Exception:
                    pass
                page.wait_for_timeout(800)

            # Try clicking many candidate selectors
            candidates = [
                "Portföy",
                "Portfoy",
                "Varlık",
                "Varlik",
                "Dağılım",
                "Dagilim",
                "KAP",
                "Detaylı",
                "Bilgileri",
                "Portföy Dağılımı",
                "Fon Bilgileri",
            ]
            for txt in candidates:
                try:
                    loc = page.get_by_text(txt, exact=False).first
                    if loc.count() > 0:
                        loc.click(timeout=1500)
                        page.wait_for_timeout(2500)
                except Exception:
                    pass
            # Save page HTML
            try:
                page_html_dump[url] = page.content()[:200000]
            except Exception:
                pass
            page.wait_for_timeout(2000)

        # Print summary
        seen = {}
        nav_log = []
        for r in api_calls:
            if "_navigate" in r:
                nav_log.append(r["_navigate"])
                continue
            key = (r.get("method"), r.get("url", "").split("?")[0])
            if key not in seen:
                seen[key] = r
        print("Navigations:", nav_log)
        print(f"\nUnique API endpoints touched: {len(seen)}")
        for (m, u), r in sorted(seen.items()):
            print(f"\n  {m} {u}")
            print(f"    status={r.get('status')} body_len={r.get('body_len')}")
            if r.get("post"):
                print(f"    post: {(r['post'] or '')[:200]}")
            preview = r.get("body_preview") or ""
            if preview:
                print(f"    body[:300]: {preview[:300]!r}")

        (OUT / "api_calls.json").write_text(
            json.dumps(api_calls, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        for url, html in page_html_dump.items():
            slug = url.replace("https://www.tefas.gov.tr/", "").replace("/", "_") or "root"
            (OUT / f"{slug}.html").write_text(html, encoding="utf-8")

        browser.close()


if __name__ == "__main__":
    main()
