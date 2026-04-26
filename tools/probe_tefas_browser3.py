"""Phase 3 probe with stealth patches.

Uses tf-playwright-stealth to avoid F5 TSPD bot detection.
"""
from __future__ import annotations

import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync


def main() -> None:
    out_dir = Path("tools/probe_out3")
    out_dir.mkdir(parents=True, exist_ok=True)
    requests_log: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="tr-TR",
            viewport={"width": 1366, "height": 800},
            extra_http_headers={
                "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
            },
        )
        page = ctx.new_page()
        stealth_sync(page)

        page.on("request", lambda req: requests_log.append({
            "url": req.url, "method": req.method, "rt": req.resource_type,
            "post": req.post_data,
        }))

        targets = [
            "https://www.tefas.gov.tr/",
            "https://www.tefas.gov.tr/FonKarsilastirma.aspx",
            "https://www.tefas.gov.tr/TarihselVeriler.aspx",
            "https://www.tefas.gov.tr/FonAnaliz.aspx?FonKod=MAC",
        ]
        for url in targets:
            print(f"\n=== visit {url} ===")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                print("  goto error:", e)
                continue
            try:
                page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                pass
            print("  final url:", page.url)
            print("  title   :", page.title())
            html = page.content()
            print("  html len:", len(html))
            slug = url.split("/")[-1].split("?")[0] or "root"
            (out_dir / f"{slug}.html").write_text(html, encoding="utf-8")

            # try to wait a bit longer for SPA
            page.wait_for_timeout(3000)
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            except Exception:
                pass
            page.wait_for_timeout(2000)

        # capture cookies after stealth navigation
        cookies = ctx.cookies()
        print("\ncookies after stealth:", [c["name"] for c in cookies])
        (out_dir / "cookies.json").write_text(json.dumps(cookies, indent=2), encoding="utf-8")

        api_like = [r for r in requests_log if "/api/" in r["url"] or "/_next/" in r["url"]]
        print("\napi-like requests:")
        for r in api_like[:80]:
            print("  ", r["method"], r["url"], (r["post"] or "")[:80])

        (out_dir / "requests_all.json").write_text(json.dumps(requests_log, ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / "requests_api.json").write_text(json.dumps(api_like, ensure_ascii=False, indent=2), encoding="utf-8")

        browser.close()


if __name__ == "__main__":
    main()
