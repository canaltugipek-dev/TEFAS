import re

t = open("tools/probe_detail2_out/next_decoded.txt", encoding="utf-8").read()
print("Total chars:", len(t))
print("KAPLINK occurrences:", t.count("KAPLINK"))
print("kapLink occurrences:", t.count("kapLink"))
print("PORTFOYORANI occurrences:", t.count("PORTFOYORANI"))

for m in re.finditer(r"KAPLINK", t):
    s = max(0, m.start() - 200)
    e = m.start() + 600
    print("=" * 60)
    print(f"@{m.start()}:")
    print(t[s:e])

print("\n\n--- PORTFOYORANI contexts ---\n")
for m in re.finditer(r"PORTFOYORANI", t):
    s = max(0, m.start() - 200)
    e = m.start() + 600
    print("=" * 60)
    print(f"@{m.start()}:")
    print(t[s:e])

print("\n\n--- HISSE SENEDI contexts ---\n")
for m in re.finditer(r"HISSE SENEDI", t):
    s = max(0, m.start() - 200)
    e = m.start() + 400
    print("=" * 60)
    print(f"@{m.start()}:")
    print(t[s:e])
