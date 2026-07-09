#!/usr/bin/env python3
"""
diag.py - diagnose van de post-auth telemetrie-uitlezing.

Doel: vaststellen of (a) de auth slaagt (verandert char 2558 = isAuthenticated?) en
(b) hoe telemetrie binnenkomt na auth: via 155f-reads, of via de 155e-notifier.
"""
import asyncio
import hashlib
import time

from bleak import BleakClient, BleakScanner

BASE = "-1212-efde-1523-785feabcd123"
SEC_CHAL = f"00002556{BASE}"
SEC_AUTH = f"00002557{BASE}"
SEC_2558 = f"00002558{BASE}"
REGID = f"00001564{BASE}"
REGISTER = f"0000155f{BASE}"
NOTIFIER = f"0000155e{BASE}"
KEY = bytes([0xFF] * 20)
IDS = [(0x02, 0x01), (0x02, 0x02), (0x02, 0x03), (0x03, 0x00),
       (0x04, 0x01), (0x00, 0x00), (0x04, 0x00), (0x04, 0x02)]


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


async def rd(c, ch):
    try:
        return bytes(await c.read_gatt_char(ch)).hex(" ")
    except Exception as e:
        return f"ERR {type(e).__name__}"


async def main():
    d = await find_named()
    if not d:
        print("niet gevonden - fiets wakker?")
        return
    print("fiets:", d.address)
    c = await connect_clean(d)
    t0 = time.monotonic()

    def push(_x, dd):
        print(f"  {time.monotonic()-t0:5.1f}s  155e push {bytes(dd).hex(' ')}", flush=True)

    await c.start_notify(NOTIFIER, push)
    print("2558 (isAuth) VOOR auth:", await rd(c, SEC_2558))
    chal = bytes(await c.read_gatt_char(SEC_CHAL))
    auth = hashlib.sha1(chal + KEY).digest()
    print("challenge:", chal.hex())
    print("authHash :", auth.hex())
    await c.write_gatt_char(SEC_AUTH, auth, response=True)
    await asyncio.sleep(0.9)
    print("verbonden na auth:", c.is_connected)
    print("2558 (isAuth) NA auth:", await rd(c, SEC_2558))
    print("-- registreer IDs op 1564, lees 155f, kijk naar notifier --")
    for i0, i1 in IDS:
        try:
            await c.write_gatt_char(REGID, bytes([i0, i1]), response=True)
            await asyncio.sleep(0.5)
            print(f"  reg {{0x{i0:02x},0x{i1:02x}}} -> 155f = {await rd(c, REGISTER)}", flush=True)
        except Exception as e:
            print(f"  reg {{0x{i0:02x},0x{i1:02x}}} fout {type(e).__name__}")
    print("-- 8s luisteren naar notifier --")
    await asyncio.sleep(8.0)
    try:
        await c.disconnect()
    except Exception:
        pass
    print("klaar")


if __name__ == "__main__":
    asyncio.run(main())
