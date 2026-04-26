"""KAP api ucuyor mu (objId, disclosure filter, file download)?"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

KAP_LINK = "https://www.kap.org.tr/tr/fon-bilgileri/genel/mac-marmara-capital-portfoy-hisse-senedi-tl-fonu-hisse-senedi-yogun-fon"
KAP_FILTER = "https://kap.org.tr/tr/api/disclosure/filter/FILTERYFBF"
KAP_PORTFOY_TYPE = "8aca490d502e34b801502e380044002b"
KAP_PAGE = "https://kap.org.tr/tr/Bildirim"
KAP_DL = "https://kap.org.tr/tr/api/file/download"

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}

print("1) GET kapLink page")
r = requests.get(KAP_LINK, headers=UA, timeout=45)
print(f"   status={r.status_code} len={len(r.text)}")
m = re.search(r"objId[\\\"':]+([A-Fa-f0-9]{32})", r.text)
print(f"   objId match: {m.group(1) if m else None}")

if not m:
    # try alternate patterns
    for pat in [r"obj_id[\"':\s]+([A-Fa-f0-9]{32})", r"member[\"\.]oidId[\"':\s]+([A-Fa-f0-9]{32})", r"summary/([A-Fa-f0-9]{32})", r"member-information/([A-Fa-f0-9]{32})", r"\"oid\"\s*:\s*\"([A-Fa-f0-9]{32})\""]:
        mm = re.search(pat, r.text)
        if mm:
            print(f"   alt pattern {pat!r}: {mm.group(1)}")
            break
    Path("tools/probe_detail2_out/kap_macpage.html").write_text(r.text, encoding="utf-8")
    print("   saved kap page html")
    sys.exit(0)

obj_id = m.group(1)

print(f"\n2) GET disclosure filter for {obj_id}")
url = f"{KAP_FILTER}/{obj_id}/{KAP_PORTFOY_TYPE}/365"
r = requests.get(url, headers=UA, timeout=45)
print(f"   status={r.status_code} len={len(r.text)}")
try:
    arr = r.json()
    print(f"   list type={type(arr).__name__} count={len(arr) if isinstance(arr, list) else '-'}")
    if isinstance(arr, list) and arr:
        b = (arr[0] or {}).get("disclosureBasic") or {}
        print(f"   first: idx={b.get('disclosureIndex')} date={b.get('publishDate')} title={b.get('title')!r}")
        di = b.get("disclosureIndex")
        if di:
            print(f"\n3) GET disclosure page for idx={di}")
            r3 = requests.get(f"{KAP_PAGE}/{di}", headers=UA, timeout=45)
            print(f"   status={r3.status_code} len={len(r3.text)}")
            mm = re.search(r"file/download/([a-f0-9]{32})", r3.text)
            if mm:
                fid = mm.group(1)
                print(f"   file id: {fid}")
                print(f"\n4) GET file download {fid}")
                r4 = requests.get(f"{KAP_DL}/{fid}", headers=UA, timeout=60)
                print(f"   status={r4.status_code} len={len(r4.content)} pdf_marker={r4.content[:8]!r}")
            else:
                print("   no file id in page")
                Path("tools/probe_detail2_out/kap_disclosure_page.html").write_text(r3.text, encoding="utf-8")
except Exception as e:
    print(f"   parse error: {e}")
    Path("tools/probe_detail2_out/kap_filter.txt").write_text(r.text, encoding="utf-8")
