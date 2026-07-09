#!/usr/bin/env python3
"""
request_soc.py - probeer het accu-register {0x00,0xC1} ACTIEF op te vragen (on-demand),
zoals de app dat doet, i.p.v. te wachten tot de module 't vanzelf pusht.

We proberen meerdere request-methodes en jagen op de bekende waarde 0x55 (85%):
  M1: schrijf {00,C1} naar 1564 (REGISTER_ID) -> lees 155f + kijk naar 155e-push
  M2: schrijf {00,C1} naar 155f (REGISTER)    -> lees 155f
  M3: schrijf 10-byte [00,C1,0..] naar 155f    -> lees 155f + 155e

Usage: py proto/request_soc.py [address|auto]
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
REGID = f"00001564{BASE}"
NOTIFIER = f"0000155e{BASE}"
KEY = bytes([0xFF] * 20)
BATT = bytes([0x00, 0xC1])
TARGET = 0x55  # 85%


async def find_named():
    for _ in range(6):
        devs = await BleakScanner.discover(timeout=10, return_adv=True)
        cands = [(a.rssi, d) for d, a in devs.values()
                 if "VELORETTI" in (d.name or a.local_name or "").upper()]
        if cands:
            cands.sort(reverse=True, key=lambda x: x[0])
            return cands[0][1]
    return None


async def find(addr):
    for _ in range(6):
        d = await BleakScanner.find_device_by_address(addr, timeout=12)
        if d:
            return d
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
    addr = sys.argv[1] if len(sys.argv) > 1 else "auto"
    d = await (find_named() if addr == "auto" else find(addr))
    if not d:
        print("niet gevonden - fiets wakker?")
        return
    print("fiets:", d.address, flush=True)
    c = await connect_clean(d)

    t0 = time.monotonic()

    def push(_x, dd):
        b = bytes(dd)
        hit = "  <== ACCU (0x55=85)!" if TARGET in b[2:] else ""
        print(f"{time.monotonic()-t0:5.1f}s  155e  {b.hex(' ')}  id={{0x{b[0]:02x},0x{b[1]:02x}}}{hit}", flush=True)

    await c.start_notify(NOTIFIER, push)
    chal = bytes(await c.read_gatt_char(SEC_CHAL))
    await c.write_gatt_char(SEC_AUTH, hashlib.sha1(chal + KEY).digest(), response=True)
    await asyncio.sleep(0.8)
    print("auth ok\n", flush=True)

    async def rd(tag):
        try:
            v = bytes(await c.read_gatt_char(REGISTER))
            hit = "  <== 0x55!" if TARGET in v[2:] else ""
            print(f"  [{tag}] 155f = {v.hex(' ')}{hit}", flush=True)
        except Exception as e:
            print(f"  [{tag}] 155f fout: {type(e).__name__}", flush=True)

    print("M1: {00,C1} -> 1564, dan 155f lezen + notifier kijken")
    try:
        await c.write_gatt_char(REGID, BATT, response=True)
    except Exception as e:
        print("  M1 write fout:", type(e).__name__)
    await asyncio.sleep(1.2)
    await rd("M1")

    print("M2: {00,C1} -> 155f, dan 155f lezen")
    try:
        await c.write_gatt_char(REGISTER, BATT, response=True)
    except Exception as e:
        print("  M2 write fout:", type(e).__name__)
    await asyncio.sleep(1.2)
    await rd("M2")

    print("M3: [00,C1,0..] (10 byte) -> 155f, dan 155f lezen")
    try:
        await c.write_gatt_char(REGISTER, BATT + bytes(8), response=True)
    except Exception as e:
        print("  M3 write fout:", type(e).__name__)
    await asyncio.sleep(1.5)
    await rd("M3")

    print("nog 3s luisteren...")
    await asyncio.sleep(3.0)
    try:
        await c.disconnect()
    except Exception:
        pass
    print("klaar", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
