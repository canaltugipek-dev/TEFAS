"""Phase 2: discover what the new TEFAS UI actually calls.

We capture EVERY network request URL, dump the rendered HTML, and follow
internal navigations triggered by clicking expected links.
"""
from __future__ import annotations

import json
from pathlib import Path
from playwright.sync_api import sync_playwright


def main() -> None:
    out_dir = Path("tools/probe_out")
    out_dir.mkdir(parents=True, exist_ok=True)
    requests_log: list[dict] = []
    finished_urls: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=[
            "--disable-blink-features=AutomationControlled",
        ])
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="tr-TR",
            viewport={"width": 1366, "height": 800},
        )
        # mask webdriver
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
            "Object.defineProperty(navigator,'languages',{get:()=>['tr-TR','tr','en-US','en']});"
            "Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});"
        )
        page = ctx.new_page()

        page.on("request", lambda req: requests_log.append({
            "url": req.url, "method": req.method, "rt": req.resource_type,
            "post": req.post_data,
        }))
        page.on("requestfinished", lambda req: finished_urls.append(req.url))

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
                page.wait_for_load_state("networkidle", timeout=30000)
            except Exception:
                pass
            print("  final url:", page.url)
            print("  title   :", page.title())
            html = page.content()
            print("  html len:", len(html))
            slug = url.replace("https://www.tefas.gov.tr/", "").replace("/", "_") or "root"
            (out_dir / f"{slug}.html").write_text(html, encoding="utf-8")

            # try simple in-page interactions: scroll a bit, wait
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2000)
            except Exception:
                pass

        # In case there's a redirect to a new domain, capture all distinct hosts
        hosts = sorted({u.split("/")[2] for u in finished_urls if u.startswith("http")})
        print("\nhosts touched:", hosts)

        # filter and print api-like requests
        api_like = [r for r in requests_log if "/api/" in r["url"] or "/_next/data/" in r["url"]]
        print("\napi-like requests:")
        for r in api_like[:80]:
            print("  ", r["method"], r["url"], (r["post"] or "")[:80])

        (out_dir / "requests_all.json").write_text(json.dumps(requests_log, ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / "requests_api.json").write_text(json.dumps(api_like, ensure_ascii=False, indent=2), encoding="utf-8")

        browser.close()


if __name__ == "__main__":
    main()
