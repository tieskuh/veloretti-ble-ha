#!/usr/bin/env python3
"""
probe_registers.py - hunt for unknown Comodule registers (odometer, charge
current, lights, range, cadence) on a *comodule-2020* Veloretti, to extend the
Home Assistant integration.

WATCH MODE (recommended): one continuous logging session per test. You change
ONE thing while it logs, and it records exactly which register/byte moved and
when. It watches two channels at once:

  * the notifier `155e` — the module PUSHES a register the moment its value
    changes (this instantly reveals lights / charge / speed toggles);
  * a polling loop over all candidate register-IDs — catches values that change
    but are not pushed (e.g. the odometer ticking up while you ride).

It also VALUE-SCANS every register against the app's known odometer readings
(odometer = 1244400 m = 1244.4 km, envioloOdometer = 1207.1 km) and flags any
byte-window that matches — so the odometer is spotted even at standstill.

RUN THREE TESTS (each one continuous log; narrate as you go):
  1. Lights:  py proto/probe_registers.py lights 60
       -> a few sec rest, then LIGHT ON, wait ~10s, LIGHT OFF, wait ~10s.
  2. Charger: py proto/probe_registers.py charger 60
       -> rest, CHARGER IN, wait ~10s, CHARGER OUT, wait ~10s.
  3. Cycling: py proto/probe_registers.py cycling 180
       -> rest, then ROLL/PEDAL a bit (keep the laptop near the bike), then rest.
          Longer, because the odometer only ticks up while actually moving.

Each run saves a full timeline to captures/watch-<label>.json — send me that file.

SAFETY (hard rule): this script only ever WRITES the 2-byte register-ID to char
`1564` and READS char `155f`. It NEVER writes a 10-byte payload to `155f` — that
is the settings-WRITE path and would change bike settings. Reads are harmless.

Usage: py proto/probe_registers.py <label> [seconds]
"""
import asyncio
import hashlib
import json
import os
import sys
import time

from bleak import BleakClient, BleakScanner

BASE = "-1212-efde-1523-785feabcd123"
SEC_CHAL = f"00002556{BASE}"
SEC_AUTH = f"00002557{BASE}"
REGISTER = f"0000155f{BASE}"   # READ ONLY here (never write 10 bytes to this!)
REGID = f"00001564{BASE}"      # write the 2-byte register-id to select
NOTIFIER = f"0000155e{BASE}"   # module pushes changed registers here
KEY = bytes([0xFF] * 20)

CAP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "captures")

# Sanity anchors (known values) + the tiered candidate list to poll.
ANCHORS = [(0x00, 0xC0), (0x00, 0xC1), (0x02, 0x50), (0x00, 0xC3)]
TIER1 = [(0x00, b) for b in (0xC2, 0xC4, 0xC5, 0xC6, 0xC7, 0xC8, 0xC9,
                             0xCA, 0xCB, 0xCC, 0xCD, 0xCE, 0xCF)] \
        + [(0x00, b) for b in range(0xB8, 0xC0)] \
        + [(0x00, b) for b in range(0xD0, 0xD8)]
# Walker73's motion/total(odometer)/ride page was {02,01/02/03} — sweep it whole.
TIER_MOTION = [(0x02, b) for b in range(0x00, 0x10)]
TIER2 = [(0x02, b) for b in range(0x51, 0x60)]
TIER3 = [(0x04, b) for b in range(0x00, 0x11)]
TIER4 = [(0x03, b) for b in range(0x00, 0x10)]
CANDIDATES = ANCHORS + TIER1 + TIER_MOTION + TIER2 + TIER3 + TIER4

# Known app values (iPhone cache, Nov 2025). The odometer only grows, so ranges
# run upward from the cached value. The module encodes multi-byte values
# big-endian (confirmed on motion {00,c3}), so we scan big-endian only.
TARGETS = [
    ("ODOMETER m (~1244400)", 1_244_400, 1_700_000),
    ("ODOMETER 0.1km (~12444)", 12_444, 17_000),
    ("ODOMETER 0.01km (~124440)", 124_440, 170_000),
    ("ENVIOLO 0.1km (~12071)", 12_071, 17_000),
    ("ENVIOLO km (~1207)", 1_207, 2_000),
]


def id_key(i0, i1):
    return f"{i0:02x}{i1:02x}"


def scan_value(payload):
    """Return list of 'LABEL=value @where' for byte-windows matching a target."""
    hits = []
    for width in (2, 3, 4):
        for off in range(0, len(payload) - width + 1):
            v = int.from_bytes(payload[off:off + width], "big")
            for label, lo, hi in TARGETS:
                if lo <= v <= hi:
                    hits.append(f"{label}={v} @b{off + 2}..b{off + 1 + width}")
    return hits


def changed_bytes(old, new):
    """Payload byte indices (b2..) that differ between two 10-byte packets."""
    o = [int(x, 16) for x in old.split()]
    n = [int(x, 16) for x in new.split()]
    return [
        (i, o[i], n[i])
        for i in range(2, min(len(o), len(n)))
        if o[i] != n[i]
    ]


# ---------------------------------------------------------------- BLE plumbing


async def find_named():
    for _ in range(6):
        devs = await BleakScanner.discover(timeout=10, return_adv=True)
        cands = [(a.rssi, d) for d, a in devs.values()
                 if "VELORETTI" in (d.name or a.local_name or "").upper()]
        if cands:
            cands.sort(reverse=True, key=lambda x: x[0])
            return cands[0][1]
    return None


async def find_addr(addr):
    for _ in range(6):
        d = await BleakScanner.find_device_by_address(addr, timeout=12)
        if d:
            return d
    return None


async def find_bike(addr):
    return await (find_named() if addr == "auto" else find_addr(addr))


async def connect_clean(dev):
    c = BleakClient(dev, timeout=30)
    await c.connect()
    try:
        await c.read_gatt_char(REGISTER)
        return c
    except Exception:
        pass
    try:
        await c.pair()
    except Exception:
        pass
    try:
        await c.disconnect()
    except Exception:
        pass
    await asyncio.sleep(1.5)
    c = BleakClient(dev, timeout=30)
    await c.connect()
    return c


async def read_register(c, i0, i1):
    """Select a register (write id -> 1564) and read its 10-byte packet."""
    await c.write_gatt_char(REGID, bytes([i0, i1]), response=True)
    await asyncio.sleep(0.05)
    return bytes(await c.read_gatt_char(REGISTER))


# --------------------------------------------------------------------- watch


async def watch(label, seconds, addr="auto"):
    d = await find_bike(addr)
    if not d:
        print("niet gevonden - fiets wakker? (druk op de aan-knop / lader erin)")
        return
    print(f"fiets: {d.address}  ({d.name})  test={label}  duur={seconds}s", flush=True)
    c = await connect_clean(d)

    chal = bytes(await c.read_gatt_char(SEC_CHAL))
    await c.write_gatt_char(SEC_AUTH, hashlib.sha1(chal + KEY).digest(), response=True)
    await asyncio.sleep(0.7)

    t0 = time.monotonic()
    events = []

    def stamp():
        return round(time.monotonic() - t0, 1)

    def note_for(payload):
        hits = scan_value(payload)
        return ("  <== " + "  ".join(hits)) if hits else ""

    # 1) Notifier: the module pushes changed registers here.
    def on_push(_ch, data):
        b = bytes(data)
        if len(b) < 2:
            return
        payload = b[2:10]
        note = note_for(payload)
        line = f"[{stamp():6}s] PUSH  {{{b[0]:02x},{b[1]:02x}}}  {b.hex(' ')}{note}"
        print(line, flush=True)
        events.append({"t": stamp(), "kind": "push", "id": id_key(b[0], b[1]),
                       "raw": b.hex(" "), "note": note.strip(" <=")})

    await c.start_notify(NOTIFIER, on_push)

    # 2) Baseline sweep (the "rust" reference). Flag the odometer already here.
    last = {}
    for i0, i1 in CANDIDATES:
        try:
            p = await read_register(c, i0, i1)
        except Exception:
            continue
        if len(p) < 10 or p[0] != i0 or p[1] != i1:
            continue
        key = id_key(i0, i1)
        last[key] = p.hex(" ")
        note = note_for(p[2:10])
        if note and (i0, i1) not in ANCHORS:
            print(f"[  0.0s] BASE  {{{i0:02x},{i1:02x}}}  {p.hex(' ')}{note}", flush=True)
            events.append({"t": 0.0, "kind": "baseline", "id": key,
                           "raw": p.hex(" "), "note": note.strip(" <=")})

    print(f"\n>>> baseline klaar. WIJZIG NU je toestand ({label}) — narrate wat je doet.\n",
          flush=True)

    # 3) Poll loop: log any register whose bytes change vs the last read.
    try:
        while time.monotonic() - t0 < seconds:
            for i0, i1 in CANDIDATES:
                try:
                    p = await read_register(c, i0, i1)
                except Exception:
                    continue
                if len(p) < 10 or p[0] != i0 or p[1] != i1:
                    continue
                key = id_key(i0, i1)
                hx = p.hex(" ")
                prev = last.get(key)
                if prev is not None and prev != hx:
                    ch = changed_bytes(prev, hx)
                    delta = ", ".join(f"b{i}: {o}->{n}" for i, o, n in ch)
                    note = note_for(p[2:10])
                    print(f"[{stamp():6}s] CHG   {{{i0:02x},{i1:02x}}}  {delta}{note}",
                          flush=True)
                    events.append({"t": stamp(), "kind": "change", "id": key,
                                   "raw": hx, "delta": delta, "note": note.strip(" <=")})
                last[key] = hx
    except KeyboardInterrupt:
        print("\n(afgebroken)", flush=True)

    os.makedirs(CAP_DIR, exist_ok=True)
    path = os.path.join(CAP_DIR, f"watch-{label}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"label": label, "address": d.address, "seconds": seconds,
                   "baseline": last, "events": events}, f, indent=1)
    print(f"\nopgeslagen: {path}   ({len(events)} events)", flush=True)
    try:
        await c.stop_notify(NOTIFIER)
    except Exception:
        pass
    try:
        await c.disconnect()
    except Exception:
        pass


async def sweep_map(max_page):
    """Read EVERY register-id 0x0000..(max_page)0xFF once, at standstill, and
    report which ones are supported + any that hold an odometer-sized value.

    The odometer is a static total, so no movement is needed; at rest the
    value-scan gives no false positives (speed/motion are 0)."""
    d = await find_named()
    if not d:
        print("niet gevonden - fiets wakker? (druk op de aan-knop / lader erin)")
        return
    print(f"fiets: {d.address}  ({d.name})  MAP 0x0000..0x{max_page:02x}ff", flush=True)
    c = await connect_clean(d)
    chal = bytes(await c.read_gatt_char(SEC_CHAL))
    await c.write_gatt_char(SEC_AUTH, hashlib.sha1(chal + KEY).digest(), response=True)
    await asyncio.sleep(0.7)
    print("auth ok — dit duurt ~2-3 min, houd de fiets wakker\n", flush=True)

    supported = {}
    t0 = time.monotonic()
    for i0 in range(0, max_page + 1):
        for i1 in range(0, 0x100):
            try:
                await c.write_gatt_char(REGID, bytes([i0, i1]), response=True)
                await asyncio.sleep(0.03)
                p = bytes(await c.read_gatt_char(REGISTER))
            except Exception:
                continue
            if len(p) < 10 or p[0] != i0 or p[1] != i1:
                continue  # id not echoed -> unsupported
            supported[id_key(i0, i1)] = p.hex(" ")
            hits = scan_value(p[2:10])
            flag = ("  <== " + "  ".join(hits)) if hits else ""
            payload = p[2:10]
            body = " ".join(f"{b}" for b in payload) if any(payload) else "(leeg)"
            print(f"  {{{i0:02x},{i1:02x}}}  {p.hex(' '):<28}  {body}{flag}", flush=True)
        print(f"  ... pagina 0x{i0:02x} klaar ({time.monotonic()-t0:.0f}s)", flush=True)

    os.makedirs(CAP_DIR, exist_ok=True)
    path = os.path.join(CAP_DIR, "probe-map.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"map": True, "address": d.address, "supported": supported}, f, indent=1)
    print(f"\n{len(supported)} ondersteunde registers -> {path}", flush=True)
    try:
        await c.disconnect()
    except Exception:
        pass


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "map":
        max_page = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x05
        try:
            asyncio.run(sweep_map(max_page))
        except KeyboardInterrupt:
            pass
        return
    label = sys.argv[1] if len(sys.argv) > 1 else "probe"
    seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    addr = sys.argv[3] if len(sys.argv) > 3 else "auto"
    try:
        asyncio.run(watch(label, seconds, addr))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
