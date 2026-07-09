#!/usr/bin/env python3
"""
long_capture.py - lange passieve notifier-capture (zoals de SDK: alleen abonneren).

We abonneren op 155e VOOR de auth (om een eventuele snapshot bij auth te vangen), doen de
handshake, en luisteren daarna lang mee. Bedoeld om een zeldzame accu-push (bij SOC-wijziging)
op te vangen terwijl de fiets laadt. Houd de fiets stil (geen wiel/knoppen).

Usage: py proto/long_capture.py [seconden]   (default 300)
"""
import asyncio
import hashlib
import sys
import time

from bleak import BleakClient, BleakScanner

BASE = "-1212-efde-1523-785feabcd123"
SEC_CHAL = f"00002556{BASE}"
SEC_AUTH = f"00002557{BASE}"
REGISTER = f"0000155f{BASE}"
NOTIFIER = f"0000155e{BASE}"
KEY = bytes([0xFF] * 20)


async def find_named():
    for _ in range(6):
        devs = await BleakScanner.discover(timeout=10, return_adv=True)
        cands = [(a.rssi, d) for d, a in devs.values()
                 if "VELORETTI" in (d.name or a.local_name or "").upper()]
        if cands:
            cands.sort(reverse=True, key=lambda x: x[0])
            return cands[0][1]
    return None


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


async def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 300.0
    d = await find_named()
    if not d:
        print("niet gevonden - fiets wakker?")
        return
    print("fiets:", d.address, flush=True)
    c = await connect_clean(d)

    t0 = time.monotonic()
    seen = {}

    def push(_x, dd):
        b = bytes(dd)
        k = (b[0], b[1])
        hexv = b.hex(" ")
        prev = seen.get(k)
        seen[k] = hexv
        tag = "  *NIEUW REGISTER*" if prev is None else ("" if prev == hexv else "  (gewijzigd)")
        print(f"{time.monotonic()-t0:6.1f}s  {hexv}  id={{0x{b[0]:02x},0x{b[1]:02x}}}{tag}", flush=True)

    await c.start_notify(NOTIFIER, push)   # abonneer eerst
    try:
        chal = bytes(await c.read_gatt_char(SEC_CHAL))
        await c.write_gatt_char(SEC_AUTH, hashlib.sha1(chal + KEY).digest(), response=True)
        await asyncio.sleep(0.8)
        print("auth ok", flush=True)
    except Exception as e:
        print("auth fout:", type(e).__name__, e, flush=True)

    print(f"--- {secs:.0f}s passief luisteren; laat de fiets met rust (aan + lader) ---", flush=True)
    end = t0 + secs
    while time.monotonic() < end and c.is_connected:
        await asyncio.sleep(2.0)
    print(f"verbonden gebleven: {c.is_connected}", flush=True)
    print("=== alle geziene registers ===", flush=True)
    for k, v in sorted(seen.items()):
        print(f"  {{0x{k[0]:02x},0x{k[1]:02x}}} = {v}", flush=True)
    try:
        await c.disconnect()
    except Exception:
        pass
    print("klaar", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
