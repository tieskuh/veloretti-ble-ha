#!/usr/bin/env python3
"""Second pass: full row dump + c1 events + ride segmentation."""
import re, datetime as dt
from pathlib import Path

CAP = Path("captures/request-data.txt")
hexpair = re.compile(r"\b([0-9a-fA-F]{2})\b")

out = bytearray()
for line in CAP.read_text(encoding="utf-8", errors="replace").splitlines():
    if "f0 cd" not in line:
        continue
    after = line.split("f0 cd", 1)[1].split("id=", 1)[0]
    b = [int(h, 16) for h in hexpair.findall(after)]
    out.extend(b[:8])

text = bytes(out).decode("latin1").replace("\x00", "")
rows = [r for r in re.split(r"\r\n|\n", text) if r.strip()]

def fmt(ts):
    return dt.datetime.fromtimestamp(int(ts), dt.UTC).strftime("%m-%d %H:%M:%S")

parsed = []
for r in rows:
    f = r.split(";")
    if f and f[-1] == "":
        f = f[:-1]
    if f and f[0].isdigit() and len(f[0]) == 10:
        parsed.append(f)

print("ALL", len(parsed), "ROWS  (idx | localtimeUTC | c1 c2 c3 c4 c5)")
prev = None
for i, f in enumerate(parsed):
    ts = int(f[0])
    gap = "" if prev is None else f"  (+{ts-prev}s)"
    c = (f + [""] * 6)[1:6]
    print(f"{i:2d} {fmt(ts)}  c1={c[0]:>2} c2={c[1]:>2} c3={c[2]:>2} c4={c[3]:>3} c5={c[4]:>5}{gap}")
    prev = ts

print("\nc1 (non-empty) events:")
for i, f in enumerate(parsed):
    if len(f) > 1 and f[1] != "":
        print(f"  idx{i} {fmt(int(f[0]))} c1={f[1]}  c4={f[4] if len(f)>4 else ''} c5={f[5] if len(f)>5 else ''}")

print("\nc4 (SOC) events with running delta:")
prevs = None
for i, f in enumerate(parsed):
    if len(f) > 4 and f[4] != "":
        v = int(f[4])
        d = "" if prevs is None else f" (d={v-prevs})"
        print(f"  idx{i} {fmt(int(f[0]))} SOC={v}{d}")
        prevs = v

# c5 speed distribution buckets
c5 = [int(f[5]) for f in parsed if len(f) > 5 and f[5] != ""]
print(f"\nc5 count={len(c5)} min={min(c5)} max={max(c5)} "
      f"mean={sum(c5)/len(c5):.0f}  (=/100 km/h: mean={sum(c5)/len(c5)/100:.2f})")
zero = sum(1 for v in c5 if v == 0)
print(f"  c5==0 (stops): {zero};  c5 in 2000..3000: {sum(1 for v in c5 if 2000<=v<=3000)}")
