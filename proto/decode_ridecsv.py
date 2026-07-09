#!/usr/bin/env python3
"""Reconstruct the ride-data CSV from the f0/cd BLE dump and analyze columns."""
import re
import sys
from pathlib import Path

CAP = Path("captures/request-data.txt")

def extract_payload(path: Path) -> bytes:
    """From each line containing 'f0 cd', grab the 8 hex bytes after 'f0 cd'."""
    out = bytearray()
    hexpair = re.compile(r"\b([0-9a-fA-F]{2})\b")
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "f0 cd" not in line:
            continue
        # cut everything before (and including) the 'f0 cd' marker, then stop at 'id='
        after = line.split("f0 cd", 1)[1]
        after = after.split("id=", 1)[0]
        bytez = [int(h, 16) for h in hexpair.findall(after)]
        # exactly the 8 payload bytes b2..b9
        out.extend(bytez[:8])
    return bytes(out)

def main():
    raw = extract_payload(CAP)
    text = raw.decode("latin1")

    print("=" * 70)
    print("RAW RECONSTRUCTED STREAM (repr, first 1200 chars)")
    print("=" * 70)
    print(repr(text[:1200]))
    print()

    # Trailing NULs come from the last padded frame(s); strip them.
    text_clean = text.replace("\x00", "")

    # Split into rows on CRLF (also tolerate lone LF)
    rows_raw = re.split(r"\r\n|\n", text_clean)

    print("=" * 70)
    print("RECONSTRUCTED CSV TEXT (first 40 lines, verbatim)")
    print("=" * 70)
    for i, r in enumerate(rows_raw[:40]):
        print(f"{i:3d}| {r}")
    print()

    # Parse rows shaped like timestamp;c1;c2;c3;c4;c5;
    parsed = []
    for r in rows_raw:
        if not r.strip():
            continue
        fields = r.split(";")
        # Trailing ';' produces a final empty field; drop a single trailing empty
        if fields and fields[-1] == "":
            fields = fields[:-1]
        parsed.append(fields)

    # Report field-count distribution
    from collections import Counter
    widths = Counter(len(f) for f in parsed)
    print("=" * 70)
    print("FIELD-COUNT DISTRIBUTION (fields per row after dropping trailing ';')")
    print("=" * 70)
    for w, c in sorted(widths.items()):
        print(f"  {w} fields: {c} rows")
    print(f"  total parsed non-empty rows: {len(parsed)}")
    print()

    # Keep rows whose first field is a 10-digit epoch (163... / 166...)
    def is_ts(s):
        return s.isdigit() and len(s) == 10

    good = [f for f in parsed if f and is_ts(f[0])]
    print(f"rows with 10-digit epoch timestamp in col0: {len(good)}")
    print()

    # Determine number of data columns (max)
    ncol = max((len(f) for f in good), default=0)
    print(f"max columns (incl timestamp): {ncol}  -> data cols c1..c{ncol-1}")
    print()

    # Print first 30 good rows verbatim (reassembled with ';')
    print("=" * 70)
    print("FIRST 30 TIMESTAMPED ROWS (verbatim, reassembled)")
    print("=" * 70)
    for f in good[:30]:
        print("  " + ";".join(f) + ";")
    print()

    # Also show human-readable timestamps for first & last
    import datetime as dt
    def fmt(ts):
        return dt.datetime.utcfromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S UTC")
    if good:
        print(f"first ts {good[0][0]} = {fmt(good[0][0])}")
        print(f"last  ts {good[-1][0]} = {fmt(good[-1][0])}")
        print(f"n rows = {len(good)}  span = {int(good[-1][0])-int(good[0][0])} s")
    print()

    # Column analysis
    print("=" * 70)
    print("PER-COLUMN ANALYSIS")
    print("=" * 70)
    # transpose; only use rows with the full column count for clean stats,
    # but also report how many rows have each col present
    for ci in range(ncol):
        vals_str = [f[ci] for f in good if ci < len(f)]
        # numeric parse (skip empties)
        nums = []
        empties = 0
        nonnum = 0
        for v in vals_str:
            if v == "":
                empties += 1
                continue
            try:
                nums.append(int(v))
            except ValueError:
                try:
                    nums.append(float(v))
                    nonnum += 1
                except ValueError:
                    nonnum += 1
        label = "timestamp(c0)" if ci == 0 else f"c{ci}"
        print(f"--- {label} ---")
        print(f"    present={len(vals_str)} empties={empties} nonint={nonnum}")
        if nums:
            mn, mx = min(nums), max(nums)
            print(f"    min={mn} max={mx} range={mx-mn}")
            # monotonic non-decreasing?
            mono_nd = all(b >= a for a, b in zip(nums, nums[1:]))
            mono_inc = all(b > a for a, b in zip(nums, nums[1:]))
            print(f"    monotonic_non_decreasing={mono_nd} strictly_increasing={mono_inc}")
            # step stats (consecutive diffs)
            diffs = [b - a for a, b in zip(nums, nums[1:])]
            if diffs:
                dc = Counter(diffs)
                common = dc.most_common(8)
                print(f"    diff min={min(diffs)} max={max(diffs)} "
                      f"mean={sum(diffs)/len(diffs):.3f}")
                print(f"    most common diffs: {common}")
            # sample first 25 values
            print(f"    first 25 values: {nums[:25]}")
    print()

    # Focused cross-check: c4 (SOC?) and c5 (speed*100?) using the max col layout.
    print("=" * 70)
    print("HYPOTHESIS CHECKS")
    print("=" * 70)
    # Build clean matrix of rows that have exactly ncol columns
    full = [f for f in good if len(f) == ncol]
    print(f"rows with full {ncol} columns: {len(full)}")
    if full and ncol >= 6:
        c4 = []
        c5 = []
        for f in full:
            try:
                c4.append(int(f[4]))
            except ValueError:
                pass
            try:
                c5.append(int(f[5]))
            except ValueError:
                pass
        if c4:
            print(f"c4: min={min(c4)} max={max(c4)}  (SOC 0..100 check)")
            print(f"    values in 0..100: {sum(1 for v in c4 if 0<=v<=100)}/{len(c4)}")
        if c5:
            print(f"c5: min={min(c5)} max={max(c5)}")
            print(f"    /100 -> min={min(c5)/100:.2f} max={max(c5)/100:.2f} km/h")

if __name__ == "__main__":
    main()
