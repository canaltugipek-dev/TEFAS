"""SUR/TZD/Z* fonlarinda objId regex'lerinin neden patlamadigini incele."""
from __future__ import annotations
import sys, re
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fon_hisse_scraper import _session, _kap_request, _OBJ_ID_PATTERNS  # noqa: E402

CODES = {
    "SUR": "https://www.kap.org.tr/tr/fon-bilgileri/genel/sur-emaa-blue-portfoy-surdurulebilirlik-hisse-senedi-fonu-hisse-senedi-yogun-fon",
    "TZD": "https://www.kap.org.tr/tr/fon-bilgileri/genel/tzd-ziraat-portfoy-hisse-senedi-fonu-hisse-senedi-yogun-fon",
    "ZHH": "https://www.kap.org.tr/tr/fon-bilgileri/genel/zhh-ziraat-portfoy-halkbank-surdurulebilirlik-30-sirketleri-hisse-senedi-fonu-hisse-senedi-yogun-fon",
    "ZJL": "https://www.kap.org.tr/tr/fon-bilgileri/genel/zjl-ziraat-portfoy-bist-100-disi-sirketler-hisse-senedi-fonu-hisse-senedi-yogun-fon",
    "RBH": "https://www.kap.org.tr/tr/fon-bilgileri/genel/rbh-albaraka-portfoy-katilim-hisse-senedi-fonu-hisse-senedi-yogun-fon",
    "HBU": "https://www.kap.org.tr/tr/fon-bilgileri/genel/hbu-hsbc-portfoy-bist-30-endeksi-hisse-senedi-fonu-hisse-senedi-yogun-fon",
}

OUT = ROOT / "data" / "_objid_debug"
OUT.mkdir(parents=True, exist_ok=True)

sess = _session()
for code, url in CODES.items():
    r = _kap_request(sess, url, timeout=45)
    if not r or not r.ok:
        print(f"{code}: HTTP fail")
        continue
    text = r.text
    (OUT / f"{code}.html").write_text(text, encoding="utf-8")
    print(f"\n========== {code}  (len={len(text)}) ==========")

    found_any = False
    for pat in _OBJ_ID_PATTERNS:
        m = re.search(pat, text)
        if m:
            print(f"  MATCH ({pat[:50]}): {m.group(1)}")
            found_any = True
    # all 32-hex strings
    hexes = sorted(set(re.findall(r"[A-Fa-f0-9]{32}", text)))
    print(f"  32hex unique: {len(hexes)}")
    for h in hexes[:8]:
        print(f"    -> {h}")

    # arama: objId / mkkMemberOid / oid yakindaki context
    for keyword in ("objId", "mkkMemberOid", "memberOid", "fundOid", "instrumentOid", "mkk"):
        ms = list(re.finditer(rf"{keyword}", text))
        if ms:
            for m in ms[:3]:
                start = max(0, m.start()-30); end = min(len(text), m.end()+60)
                print(f"  ctx[{keyword}]: ...{text[start:end]!r}...")
            break
