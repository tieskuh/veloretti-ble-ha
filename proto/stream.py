#!/usr/bin/env python3
"""
stream.py - authenticeer en leg daarna de volledige notifier-stream vast.

Doel: alle auto-gestreamde registers verzamelen en (met bekende waarden) decoderen
welk register = accu / snelheid / laadstroom is.

Usage: py proto/stream.py [seconden]   (default 60)
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
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
    d = await find_named()
    if not d:
        print("niet gevonden - fiets wakker?")
        return
    print("fiets:", d.address, flush=True)
    c = await connect_clean(d)
    chal = bytes(await c.read_gatt_char(SEC_CHAL))
    auth = hashlib.sha1(chal + KEY).digest()
    await c.write_gatt_char(SEC_AUTH, auth, response=True)
    await asyncio.sleep(0.8)
    print("geauthenticeerd, notifier-capture start", flush=True)

    t0 = time.monotonic()

    def push(_x, dd):
        d = bytes(dd)
        print(f"{time.monotonic()-t0:6.1f}s  {d.hex(' ')}  id={{0x{d[0]:02x},0x{d[1]:02x}}}", flush=True)

    await c.start_notify(NOTIFIER, push)
    print(f"--- {secs:.0f}s capturen: laat ~15s settelen, draai dan het achterwiel ---", flush=True)
    await asyncio.sleep(secs)
    try:
        await c.disconnect()
    except Exception:
        pass
    print("klaar", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
