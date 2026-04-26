"""HTML'den Next.js __next_f.push gomulu JSON streamlerini ayikla, MAC ile ilgili bilgileri ara."""
import re
import json
from pathlib import Path

p = Path("tools/probe_detail2_out/tr_fon-detayli-analiz_MAC.html")
html = p.read_text(encoding="utf-8")

# Find all chunks pushed via self.__next_f.push([N,"..."])
chunks = re.findall(r"self\.__next_f\.push\(\[\s*\d+\s*,\s*\"((?:\\.|[^\"\\])*)\"\]\)", html)
print(f"Chunks: {len(chunks)}")

decoded_all = ""
for c in chunks:
    try:
        decoded = bytes(c, "utf-8").decode("unicode_escape")
    except Exception:
        decoded = c
    decoded_all += decoded + "\n----CHUNK----\n"

Path("tools/probe_detail2_out/next_decoded.txt").write_text(decoded_all, encoding="utf-8")
print(f"Decoded len: {len(decoded_all)}")

for kw in ["KAPLINK", "kapLink", "kapUrl", "MkkMemberOidId", "mkkMember", "PORTFOYORANI", "fundAllocation", "varlikDagilim", "HISSE SENEDI", "kap.org.tr", "obj_id", "objId", "disclosureType"]:
    cnt = decoded_all.lower().count(kw.lower())
    print(f"{kw}: {cnt}")

# print snippets around kap.org.tr
for m in re.finditer(r"kap\.org\.tr[^\"\\\s]{0,100}", decoded_all, re.IGNORECASE):
    print("KAP:", m.group(0))
