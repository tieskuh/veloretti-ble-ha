#!/usr/bin/env python3
"""
request_data.py - stuur het Comodule "DTC request-data"-commando en vang de register-burst.

Ontdekt in de SDK (g8_0 = sendDtcCommandUseCase, h8_0 encoder, W1 = DtcCommand):
  commando = register {0xF0,0xDC} met payload [requestData, acknowledge, 0,0,0,0,0,0]
  W1.c = (requestData=true, acknowledge=false)  ->  F0 DC 01 00 00 00 00 00 00 00
geschreven naar de REGISTER-char 155f. Daarop zendt de module al z'n registers uit op 155e
(zoals de app doet -> "SOC binnen seconden"). Dit is de actieve trigger.

Usage: py proto/request_data.py [address|auto]
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

DTC_REQ = bytes([0xF0, 0xDC, 0x01, 0x00, 0, 0, 0, 0, 0, 0])   # requestData=1, ack=0
DTC_ACK = bytes([0xF0, 0xDC, 0x01, 0x01, 0, 0, 0, 0, 0, 0])   # requestData=1, ack=1


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


def decode(d):
    idp = (d[0], d[1])
    if idp == (0x02, 0x50): return f"snelheid? b2={d[2]}"
    if idp == (0x00, 0xc0): return f"assist? b2={d[2]}"
    if idp == (0x00, 0xc3): return f"beweging? u16={d[2]|d[3]<<8}"
    # accu-kandidaat: byte in 0..100 buiten de bekende bewegingsregisters
    cand = [f"b{i}={b}" for i, b in enumerate(d[2:], 2) if 1 <= b <= 100]
    return ("KANDIDAAT " + " ".join(cand)) if cand else ""


async def main():
    addr = sys.argv[1] if len(sys.argv) > 1 else "auto"
    d = await (find_named() if addr == "auto" else find(addr))
    if not d:
        print("niet gevonden - fiets wakker?")
        return
    print("fiets:", d.address, flush=True)
    c = await connect_clean(d)

    t0 = time.monotonic()
    seen = {}

    def push(_x, dd):
        b = bytes(dd)
        seen[(b[0], b[1])] = b
        print(f"{time.monotonic()-t0:6.1f}s  {b.hex(' ')}  id={{0x{b[0]:02x},0x{b[1]:02x}}}  {decode(b)}", flush=True)

    await c.start_notify(NOTIFIER, push)
    chal = bytes(await c.read_gatt_char(SEC_CHAL))
    await c.write_gatt_char(SEC_AUTH, hashlib.sha1(chal + KEY).digest(), response=True)
    await asyncio.sleep(0.8)
    print("auth ok. --- DTC request-data (F0 DC 01 00 ..) -> 155f ---", flush=True)
    try:
        await c.write_gatt_char(REGISTER, DTC_REQ, response=True)
    except Exception as e:
        print("  write 155f fout:", type(e).__name__, e, flush=True)
    await asyncio.sleep(7.0)

    print("--- variant: acknowledge=1 ---", flush=True)
    try:
        await c.write_gatt_char(REGISTER, DTC_ACK, response=True)
    except Exception:
        pass
    await asyncio.sleep(5.0)

    print("--- variant: DTC naar 1564 ---", flush=True)
    try:
        await c.write_gatt_char(REGID, DTC_REQ, response=True)
    except Exception as e:
        print("  1564 fout:", type(e).__name__)
    await asyncio.sleep(5.0)

    print(f"\n=== unieke registers gezien: {len(seen)} ===", flush=True)
    for (i0, i1), b in sorted(seen.items()):
        print(f"  {{0x{i0:02x},0x{i1:02x}}} = {b.hex(' ')}   {decode(b)}")
    try:
        await c.disconnect()
    except Exception:
        pass
    print("klaar", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
