#!/usr/bin/env python3
"""
handshake.py - Comodule auth-handshake + telemetrie-uitlezing voor de Veloretti.

Handshake (gereconstrueerd uit de gedecompileerde Comodule-SDK):
  o_0.java : isAuthenticated -> getPublicKey -> writeAuthHash
  v4_0.java: lees "publicKey" (20-byte challenge) van characteristic 00002556
  xa.java  : authHash = SHA1(publicKey ++ privateKey); schrijf naar 00002557
  B4.java  : privateKey-string wordt HEX-gedecodeerd
  defaultPrivateKey = "FFFFFFFFFFFFFFFF" -> 8x 0xFF

Na succesvolle auth werkt de Metrics register-selectie (1564 -> 155f / 155e).
Pairen kan de verbinding even laten vallen; daarom verbinden we na het bonden opnieuw.

Usage: py proto/handshake.py [address|auto]
"""
import asyncio
import hashlib
import sys

from bleak import BleakClient, BleakScanner

BASE = "-1212-efde-1523-785feabcd123"
SEC_CHALLENGE = f"00002556{BASE}"   # lezen: publicKey/challenge
SEC_AUTH = f"00002557{BASE}"        # schrijven: authHash
REGID = f"00001564{BASE}"
REGISTER = f"0000155f{BASE}"
NOTIFIER = f"0000155e{BASE}"

PRIVATE_KEY = bytes([0xFF] * 20)   # defaultPrivateKey "FFFF..."(8x FF) opgevuld tot 20x 0xFF
KNOWN = {
    (0x02, 0x01): "snelheid", (0x02, 0x02): "km-stand", (0x02, 0x03): "cadans/range",
    (0x03, 0x00): "settings", (0x04, 0x01): "laadstroom",
}


def u16(d, i):
    return d[i] | (d[i + 1] << 8)


def decode(idp, d):
    if len(d) < 10:
        return ""
    if idp == (0x02, 0x01):
        return f"snelheid={u16(d, 2)/100:.2f} km/h"
    if idp == (0x02, 0x02):
        return f"km-stand={u16(d, 6)/10:.1f} km"
    if idp == (0x02, 0x03):
        return f"cadans={d[3]*5} rpm, rawRange={d[8]} km"
    if idp == (0x03, 0x00):
        return f"assist={d[2]}, licht={d[4]==1}, mode={d[5]}"
    if idp == (0x04, 0x01):
        return f"laadstroom={u16(d, 6)/1000:.3f} A"
    return ""


async def find_named():
    for _ in range(6):
        devs = await BleakScanner.discover(timeout=10, return_adv=True)
        cands = [(a.rssi, d) for d, a in devs.values()
                 if "VELORETTI" in (d.name or a.local_name or "").upper()]
        if cands:
            cands.sort(key=lambda x: x[0], reverse=True)
            return cands[0][1]
    return None


async def find(addr):
    for _ in range(6):
        d = await BleakScanner.find_device_by_address(addr, timeout=12)
        if d:
            return d
    return None


async def connect_clean(dev):
    """Verbind en zorg voor een gebonde (versleutelde) link; herverbind na pairen."""
    c = BleakClient(dev, timeout=30)
    await c.connect()
    try:
        await c.read_gatt_char(REGISTER)   # lukt als al gebond
        return c
    except Exception:
        pass
    print("  pairen + opnieuw verbinden...")
    try:
        await c.pair()
    except Exception as e:
        print("  pair:", type(e).__name__)
    try:
        await c.disconnect()
    except Exception:
        pass
    await asyncio.sleep(1.5)
    c = BleakClient(dev, timeout=30)
    await c.connect()
    return c


async def reg_read(c, i0, i1):
    await c.write_gatt_char(REGID, bytes([i0, i1]), response=True)
    await asyncio.sleep(0.35)
    return bytes(await c.read_gatt_char(REGISTER))


async def handshake(c):
    chal = bytes(await c.read_gatt_char(SEC_CHALLENGE))
    auth = hashlib.sha1(chal + PRIVATE_KEY).digest()
    print(f"  challenge={chal.hex()}")
    print(f"  authHash =SHA1(chal+key)= {auth.hex()}")
    await c.write_gatt_char(SEC_AUTH, auth, response=True)
    await asyncio.sleep(0.7)
    tot = await reg_read(c, 0x02, 0x02)
    unlocked = tot[:2] == bytes([0x02, 0x02])
    print(f"  TOTAL na auth: {tot.hex(' ')}  {'<<< ONTGRENDELD' if unlocked else '(nog dicht)'}")
    return unlocked


async def read_all(c):
    def on_push(_c, dd):
        d = bytes(dd)
        print(f"  155e push {d.hex(' ')}  {decode((d[0], d[1]), d)}")
    await c.start_notify(NOTIFIER, on_push)
    for (i0, i1), nm in KNOWN.items():
        v = await reg_read(c, i0, i1)
        print(f"  {nm:14s} {{0x{i0:02x},0x{i1:02x}}}: {v.hex(' ')}   {decode((i0, i1), v)}")
    print("  -- accu-hunt {0x04,0x00..0x10} --")
    for i1 in range(0x00, 0x11):
        v = await reg_read(c, 0x04, i1)
        if any(v[2:]):
            print(f"    {{0x04,0x{i1:02x}}}: {v.hex(' ')}")
    await asyncio.sleep(2.0)


async def main():
    addr = sys.argv[1] if len(sys.argv) > 1 else "auto"
    d = await (find_named() if addr == "auto" else find(addr))
    if not d:
        print("niet gevonden - fiets wakker?")
        return
    print(f"fiets: {d.address}  ({d.name})")
    try:
        c = await connect_clean(d)
        print("verbonden, handshake...")
        chal = bytes(await c.read_gatt_char(SEC_CHALLENGE))
        auth = hashlib.sha1(chal + PRIVATE_KEY).digest()
        print(f"  challenge={chal.hex()}")
        print(f"  authHash = {auth.hex()}  (key=20x0xFF)")
        try:
            await c.write_gatt_char(SEC_AUTH, auth, response=True)
            await asyncio.sleep(0.7)
        except Exception as e:
            print("  auth-write gaf:", type(e).__name__, "- herverbinden...")
        if not c.is_connected:
            try:
                await c.disconnect()
            except Exception:
                pass
            await asyncio.sleep(1.5)
            c = await connect_clean(d)
        tot = await reg_read(c, 0x02, 0x02)
        if tot[:2] == bytes([0x02, 0x02]):
            print(f"  TOTAL: {tot.hex(' ')}  <<< ONTGRENDELD\n")
            print(">> Telemetrie ontgrendeld. Registers lezen:\n")
            await read_all(c)
        else:
            print(f"  TOTAL: {tot.hex(' ')}  (nog dicht) - nadere analyse nodig.")
        await c.disconnect()
    except Exception as e:
        print("fout:", type(e).__name__, e)


if __name__ == "__main__":
    asyncio.run(main())
