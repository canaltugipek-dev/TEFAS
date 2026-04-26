"""Headless Chromium probe for TEFAS.

- Visits FonKarsilastirma.aspx and TarihselVeriler.aspx
- Logs every network request/response
- Tries to call BindHistoryInfo from inside the page context
- Dumps resulting cookies so we can decide whether requests can reuse them
"""
from __future__ import annotations

import json
import sys
from playwright.sync_api import sync_playwright


def main() -> None:
    captured: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="tr-TR",
        )
        page = ctx.new_page()

        def on_request(req):
            if "/api/" in req.url or "BindHistoryInfo" in req.url or "BindComparison" in req.url:
                captured.append({"phase": "req", "url": req.url, "method": req.method, "headers": dict(req.headers), "post": req.post_data})

        def on_response(res):
            try:
                if "/api/" in res.url or "BindHistoryInfo" in res.url or "BindComparison" in res.url:
                    captured.append({"phase": "res", "url": res.url, "status": res.status, "ct": res.headers.get("content-type")})
            except Exception:
                pass

        page.on("request", on_request)
        page.on("response", on_response)

        # 1) FonKarsilastirma — fund list
        print("[step1] visit FonKarsilastirma.aspx")
        page.goto("https://www.tefas.gov.tr/FonKarsilastirma.aspx", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_load_state("networkidle", timeout=60000)
        print("  body bytes:", len(page.content()))
        cookies = ctx.cookies()
        print("  cookies after FK:", [c["name"] for c in cookies])

        # try clicking the search button if exists - listele
        try:
            page.evaluate("() => { const b = document.querySelector('input[type=\"button\"]#MainContent_BtnAra, button#MainContent_BtnAra, #MainContent_BtnAra'); if(b) b.click(); }")
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception as e:
            print("  click error:", e)

        # 2) TarihselVeriler
        print("[step2] visit TarihselVeriler.aspx")
        page.goto("https://www.tefas.gov.tr/TarihselVeriler.aspx", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_load_state("networkidle", timeout=60000)
        print("  body bytes:", len(page.content()))

        # 3) Try in-page POST to BindHistoryInfo with current session
        print("[step3] in-page fetch BindHistoryInfo for MAC")
        js = """
        async () => {
          const params = new URLSearchParams();
          params.set('fontip', 'YAT');
          params.set('bastarih', '01.04.2026');
          params.set('bittarih', '25.04.2026');
          params.set('fonkod', 'MAC');
          const res = await fetch('https://www.tefas.gov.tr/api/DB/BindHistoryInfo', {
            method: 'POST',
            credentials: 'include',
            headers: {
              'Accept': 'application/json, text/javascript, */*; q=0.01',
              'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
              'X-Requested-With': 'XMLHttpRequest',
              'Origin': 'https://www.tefas.gov.tr',
              'Referer': 'https://www.tefas.gov.tr/TarihselVeriler.aspx',
            },
            body: params.toString(),
          });
          const txt = await res.text();
          return { status: res.status, ct: res.headers.get('content-type'), len: txt.length, head: txt.slice(0, 300) };
        }
        """
        try:
            r = page.evaluate(js)
            print("  in-page:", r)
        except Exception as e:
            print("  evaluate error:", e)

        # 4) Try alternative endpoint guesses
        print("[step4] alternative endpoint guesses")
        for path in [
            "/api/DB/BindHistoryAllFund",
            "/api/DB/BindHistoryAllocation",
            "/api/DB/BindHistoryFundReturns",
            "/api/DB/BindFundReturns",
            "/api/DB/BindHistoryInfoFund",
            "/api/DB/BindHistoryFundInfo",
            "/api/Comparison/BindComparisonFundReturns",
            "/api/HistoricalData/BindHistoryInfo",
            "/api/HistoricalData/BindFundHistory",
            "/api/BindHistoryInfo",
        ]:
            js2 = f"""
            async () => {{
              const params = new URLSearchParams();
              params.set('fontip', 'YAT');
              params.set('bastarih', '01.04.2026');
              params.set('bittarih', '25.04.2026');
              params.set('fonkod', 'MAC');
              const res = await fetch('https://www.tefas.gov.tr{path}', {{
                method: 'POST',
                credentials: 'include',
                headers: {{
                  'Accept': 'application/json, text/javascript, */*; q=0.01',
                  'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                  'X-Requested-With': 'XMLHttpRequest',
                  'Origin': 'https://www.tefas.gov.tr',
                  'Referer': 'https://www.tefas.gov.tr/TarihselVeriler.aspx',
                }},
                body: params.toString(),
              }});
              const txt = await res.text();
              return {{ status: res.status, ct: res.headers.get('content-type'), len: txt.length, head: txt.slice(0, 200) }};
            }}
            """
            try:
                r = page.evaluate(js2)
                print(f"  {path} -> {r['status']} ct={r['ct']} len={r['len']} head={r['head']!r}")
            except Exception as e:
                print(f"  {path} -> err {e}")

        # 5) Try clicking the form on TarihselVeriler to capture real call
        print("[step5] submit TarihselVeriler form for MAC")
        try:
            page.fill('#MainContent_TextBoxFon', 'MAC')
        except Exception as e:
            print('  fill fon err', e)
        try:
            page.fill('#MainContent_TextBoxStartDate', '01.04.2026')
            page.fill('#MainContent_TextBoxEndDate', '25.04.2026')
        except Exception as e:
            print('  fill date err', e)
        try:
            page.click('#MainContent_ButtonSearchDate')
            page.wait_for_load_state('networkidle', timeout=30000)
        except Exception as e:
            print('  click search err', e)

        print("[step6] dump captured network entries (api-related):")
        for c in captured:
            print("  ", c)

        with open("tools/probe_tefas_browser_capture.json", "w", encoding="utf-8") as f:
            json.dump(captured, f, ensure_ascii=False, indent=2)

        browser.close()


if __name__ == "__main__":
    sys.exit(main())
