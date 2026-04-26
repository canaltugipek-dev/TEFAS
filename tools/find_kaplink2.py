import re

t = open("tools/probe_detail2_out/next_decoded.txt", encoding="utf-8").read()
print("Total chars:", len(t))

for m in re.finditer(r"kapLink", t):
    s = max(0, m.start() - 300)
    e = m.start() + 800
    print("=" * 60)
    print(f"@{m.start()}:")
    print(t[s:e])
    print()
