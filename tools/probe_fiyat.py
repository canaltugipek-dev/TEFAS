"""Inspect fonFiyatBilgiGetir response shape and explore historical span options."""
from __future__ import annotations

import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync


def main() -> None:
    out_dir = Path("tools/probe_fiyat")
    out_dir.mkdir(parents=True, exist_ok=True)

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

        # Warmup: visit fund detail page so cookies + Origin are right
        page.goto("https://www.tefas.gov.tr/tr/fund-detail/MAC", wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        page.wait_for_timeout(2000)
        print("warmup done")

        async_js = """
        async ([fonKodu, periyod]) => {
          const res = await fetch('https://www.tefas.gov.tr/api/funds/fonFiyatBilgiGetir', {
            method: 'POST', credentials: 'include',
            headers: {
              'Content-Type': 'application/json',
              'Accept': 'application/json',
            },
            body: JSON.stringify({fonKodu, dil: 'TR', periyod}),
          });
          const txt = await res.text();
          return { status: res.status, ct: res.headers.get('content-type'), len: txt.length, body: txt };
        }
        """
        for periyod in (1, 3, 6, 12, 24, 36, 60, 120, 240):
            r = page.evaluate(async_js, ["MAC", periyod])
            print(f"\n--- periyod={periyod} status={r['status']} len={r['len']} ---")
            if r["status"] != 200:
                print(r["body"][:300])
                continue
            data = json.loads(r["body"])
            res_list = data.get("resultList") or []
            print("resultList len:", len(res_list))
            if res_list:
                first = res_list[0]
                last = res_list[-1]
                print("keys:", list(first.keys())[:20])
                # try to spot date and price keys
                date_keys = [k for k in first.keys() if "tarih" in k.lower() or "date" in k.lower()]
                price_keys = [k for k in first.keys() if "fiyat" in k.lower() or "price" in k.lower() or "deger" in k.lower()]
                print("date_keys:", date_keys, "price_keys:", price_keys)
                print("first row:", first)
                print("last row :", last)
            (out_dir / f"MAC_periyod_{periyod}.json").write_text(r["body"], encoding="utf-8")

        # Also probe fonGetiriBazliBilgiGetir (maybe full fund universe with rates)
        getiri_js = """
        async () => {
          const body = {dil:'TR',fonTipi:'YAT',kurucuKodu:null,sfonTurKod:null,fonTurAciklama:null,islem:1,fonTurKod:null,fonGrupKod:null,fonKodu:null};
          const res = await fetch('https://www.tefas.gov.tr/api/funds/fonGetiriBazliBilgiGetir', {
            method:'POST', credentials:'include',
            headers:{'Content-Type':'application/json','Accept':'application/json'},
            body: JSON.stringify(body),
          });
          const txt = await res.text();
          return { status: res.status, len: txt.length, head: txt.slice(0, 800) };
        }
        """
        r = page.evaluate(getiri_js)
        print("\n=== fonGetiriBazliBilgiGetir ===")
        print("status", r["status"], "len", r["len"])
        print("head:", r["head"])

        browser.close()


if __name__ == "__main__":
    main()
