import re
from pathlib import Path

html = Path("tools/probe_out3/root.html").read_text(encoding="utf-8")
print("len", len(html))

# all internal hrefs
hrefs = set(re.findall(r'href="(/(?!_next)[^"#?]*)"', html))
print("internal hrefs:")
for h in sorted(hrefs):
    print(" ", h)

# api hints in HTML/JS
apis = set(re.findall(r"/api/[A-Za-z0-9/_\-]+", html))
print("\napi hints in HTML:")
for a in sorted(apis):
    print(" ", a)

# Next.js dynamic chunks listed
chunks = set(re.findall(r"/_next/static/chunks/app/[^\"']+", html))
print("\nnext app chunks (route hints):")
for c in sorted(chunks):
    print(" ", c)
