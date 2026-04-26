"""Quick diagnostic: pull TEFAS pages and dump api hints."""
from __future__ import annotations

import re
import sys
import requests

H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
}


def dump(url: str) -> None:
    s = requests.Session()
    r = s.get(url, headers=H, timeout=30)
    print(f"\n=== {url} ===")
    print("status", r.status_code, "len", len(r.text))
    # collect /api/ paths
    api = sorted(set(re.findall(r"/api/[A-Za-z0-9/_\-]+", r.text)))
    print("api paths (HTML):", api)
    # find script src refs
    srcs = re.findall(r"<script[^>]+src=\"([^\"]+)\"", r.text, flags=re.I)
    print("scripts:", srcs[:25])

    # fetch the script files and look for /api/ inside
    found: dict[str, set[str]] = {}
    for src in srcs:
        if src.startswith("//"):
            full = "https:" + src
        elif src.startswith("/"):
            full = "https://www.tefas.gov.tr" + src
        elif src.startswith("http"):
            full = src
        else:
            full = "https://www.tefas.gov.tr/" + src
        try:
            jr = s.get(full, headers=H, timeout=20)
        except Exception as e:
            found[src] = {f"<error {e}>"}
            continue
        if jr.status_code != 200 or "javascript" not in jr.headers.get("content-type", "").lower() and not src.endswith(".js"):
            found[src] = {f"<status {jr.status_code} ct={jr.headers.get('content-type')}>"}
            continue
        api2 = set(re.findall(r"/api/[A-Za-z0-9/_\-]+", jr.text))
        # also catch absolute domains
        api3 = set(re.findall(r"https?://[A-Za-z0-9.\-]+/api/[A-Za-z0-9/_\-]+", jr.text))
        if api2 or api3:
            found[src] = api2 | api3
    for k, v in found.items():
        if v:
            print(f"  {k}: {sorted(v)}")


if __name__ == "__main__":
    urls = [
        "https://www.tefas.gov.tr/TarihselVeriler.aspx",
        "https://www.tefas.gov.tr/FonKarsilastirma.aspx",
    ]
    for u in urls:
        dump(u)
