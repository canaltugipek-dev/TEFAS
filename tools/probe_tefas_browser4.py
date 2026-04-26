"""Phase 4: explore the new Next.js routes and capture all api calls + responses."""
from __future__ import annotations

import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync


def main() -> None:
    out_dir = Path("tools/probe_out4")
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
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

        api_responses: list[dict] = []

        def on_response(res):
            try:
                if "/api/" in res.url and res.request.method != "OPTIONS":
                    body = ""
                    try:
                        if "json" in (res.headers.get("content-type") or ""):
                            body = res.text()[:1500]
                    except Exception:
                        pass
                    api_responses.append({
                        "url": res.url,
                        "method": res.request.method,
                        "post": res.request.post_data,
                        "status": res.status,
                        "ct": res.headers.get("content-type"),
                        "body_snippet": body,
                    })
            except Exception as e:
                api_responses.append({"err": str(e)})

        page.on("response", on_response)

        targets = [
            "https://www.tefas.gov.tr/tr",
            "https://www.tefas.gov.tr/tr/fund-detail/MAC",
            "https://www.tefas.gov.tr/tr/fon-getirileri",
            "https://www.tefas.gov.tr/tr/fon-karsilastir",
            "https://www.tefas.gov.tr/tr/tefas-fonlar",
        ]
        for url in targets:
            print(f"\n=== visit {url} ===")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                print("  goto error:", e)
                continue
            try:
                page.wait_for_load_state("networkidle", timeout=25000)
            except Exception:
                pass
            page.wait_for_timeout(4000)
            print("  final:", page.url, "title:", page.title()[:80])
            # save html snapshot
            slug = url.replace("https://www.tefas.gov.tr/tr/", "").replace("https://www.tefas.gov.tr/tr", "tr_root").replace("/", "_") or "tr_root"
            try:
                (out_dir / f"{slug}.html").write_text(page.content(), encoding="utf-8")
            except Exception as e:
                print("  save html err", e)

            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            except Exception:
                pass
            page.wait_for_timeout(2000)

        # Print just the unique api endpoints we observed
        seen = {}
        for r in api_responses:
            key = (r.get("method"), r.get("url", "").split("?")[0])
            if key not in seen:
                seen[key] = r
        print("\nunique api endpoints:")
        for (m, u), r in sorted(seen.items()):
            print(f"  {m} {u} -> {r.get('status')} {r.get('ct')}")
            if r.get("post"):
                print(f"    post: {(r['post'] or '')[:120]}")
            snip = r.get("body_snippet")
            if snip:
                print(f"    body: {snip[:200]!r}")

        (out_dir / "api_responses.json").write_text(json.dumps(api_responses, ensure_ascii=False, indent=2), encoding="utf-8")
        browser.close()


if __name__ == "__main__":
    main()
