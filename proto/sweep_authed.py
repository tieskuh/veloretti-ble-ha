#!/usr/bin/env python3
"""
sweep_authed.py - na auth: sweep alle register-ID's en zoek het accu-register.

Hypothese: na de handshake reageert de module op register-registratie (schrijf
{ID0,ID1} naar 1564 -> de module begint dat register op 155e te pushen). We sweepen
id0 in {0x00,0x04,0x02}, id1 0..255, en verzamelen alle unieke registers die op de
notifier verschijnen. Bekende accu = 0x62 (98%); houd de fiets STIL (geen wiel) en
aan de lader, zodat bewegingsregisters stil blijven en de accu opvalt.
"""
import asyncio
import hashlib
import time

from bleak import BleakClient, BleakScanner

BASE = "-1212-efde-1523-785feabcd123"
SEC_CHAL = f"00002556{BASE}"
SEC_AUTH = f"00002557{BASE}"
REGISTER = f"0000155f{BASE}"
NOTIFIER = f"0000155e{BASE}"
REGID = f"00001564{BASE}"
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
    d = await find_named()
    if not d:
        print("niet gevonden - fiets wakker?")
        return
    print("fiets:", d.address, flush=True)
    c = await connect_clean(d)
    chal = bytes(await c.read_gatt_char(SEC_CHAL))
    await c.write_gatt_char(SEC_AUTH, hashlib.sha1(chal + KEY).digest(), response=True)
    await asyncio.sleep(0.8)
    print("geauthenticeerd, sweep start", flush=True)

    seen = {}
    t0 = time.monotonic()

    def push(_x, dd):
        b = bytes(dd)
        seen[(b[0], b[1])] = (b.hex(" "), round(time.monotonic() - t0, 1))

    await c.start_notify(NOTIFIER, push)
    for i0 in (0x00, 0x04, 0x02):
        for i1 in range(256):
            try:
                await c.write_gatt_char(REGID, bytes([i0, i1]), response=True)
            except Exception:
                pass
            await asyncio.sleep(0.06)
        print(f"  id0=0x{i0:02x} klaar, tot nu toe {len(seen)} registers", flush=True)
    await asyncio.sleep(2.0)

    print("\n=== unieke registers op de notifier ===", flush=True)
    for (i0, i1), (hx, t) in sorted(seen.items()):
        b = bytes.fromhex(hx.replace(" ", ""))
        flag = ""
        if 0x62 in b[2:] or 0x60 in b[2:] or any(90 <= x <= 100 for x in b[2:]):
            flag = "   <== ACCU-KANDIDAAT (90-100 / 0x62 / 0x60)"
        print(f"  {{0x{i0:02x},0x{i1:02x}}} = {hx}  (t={t}s){flag}", flush=True)
    try:
        await c.disconnect()
    except Exception:
        pass
    print("klaar", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
