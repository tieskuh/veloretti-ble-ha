#!/usr/bin/env python3
"""
registers.py - lees de Comodule Metrics-registers met de JUISTE framing.

Mirror van Walker73's BikeManager: schrijf {ID0,ID1} naar 1564, lees daarna 155f,
en luister tegelijk op de 155e-notifier. Elk pakket is 10 bytes: [ID0][ID1][8 payload].

Usage:
  py proto/registers.py <address>          # lees de bekende registers
  py proto/registers.py <address> --hunt   # + zoek het accu-SoC-register (0x55/0x60)

Vereist een bestaande bond (pairt automatisch de eerste keer).
"""
import asyncio
import sys

from bleak import BleakClient, BleakScanner

BASE = "-1212-efde-1523-785feabcd123"
REGID = f"00001564{BASE}"
REGISTER = f"0000155f{BASE}"
NOTIFIER = f"0000155e{BASE}"

KNOWN = {
    (0x02, 0x01): "MOTION/snelheid",
    (0x02, 0x02): "TOTAL/km-stand",
    (0x02, 0x03): "RIDE/cadans+range",
    (0x03, 0x00): "SETTINGS",
    (0x04, 0x01): "POWER/laadstroom",
    (0x00, 0x00): "MYSTERY",
}

# Bekende accu-waarden van de twee fietsen (voor de hunt): 85% en 96%.
BATTERY_HINTS = {0x55: 85, 0x60: 96}


def u16(b0: int, b1: int) -> int:
    return b0 | (b1 << 8)


def parse(idp, d: bytes) -> str:
    if len(d) < 10:
        return f"kort pakket ({len(d)} bytes)"
    out = []
    if idp == (0x02, 0x01):
        out.append(f"snelheid={u16(d[2], d[3]) / 100:.2f} km/h")
    elif idp == (0x02, 0x02):
        out.append(f"km-stand={u16(d[6], d[7]) / 10:.1f} km")
    elif idp == (0x02, 0x03):
        out.append(f"cadans={d[3] * 5} rpm, rawRange={d[8]} km")
    elif idp == (0x03, 0x00):
        out.append(f"assist={d[2]}, walk={d[3] == 0}, licht={d[4] == 1}, mode={d[5]}")
    elif idp == (0x04, 0x01):
        out.append(f"laadstroom={u16(d[6], d[7]) / 1000:.3f} A")
    for i, b in enumerate(d[2:], start=2):
        if b in BATTERY_HINTS:
            out.append(f"** b{i}=0x{b:02x}={b} ~ accu {BATTERY_HINTS[b]}%?")
    return ", ".join(out) or "(geen bekende parsing)"


async def find(addr: str):
    for _ in range(5):
        d = await BleakScanner.find_device_by_address(addr, timeout=12)
        if d:
            return d
    return None


async def read_reg(c, id0: int, id1: int) -> bytes:
    await c.write_gatt_char(REGID, bytes([id0, id1]), response=True)
    await asyncio.sleep(0.4)
    return bytes(await c.read_gatt_char(REGISTER))


async def main() -> None:
    if len(sys.argv) < 2:
        print("usage: registers.py <address> [--hunt]")
        return
    addr = sys.argv[1]
    hunt = "--hunt" in sys.argv

    dev = await find(addr)
    if not dev:
        print("niet gevonden - is de fiets wakker en de app dicht?")
        return
    c = BleakClient(dev, timeout=30)
    await c.connect()
    print("verbonden:", c.is_connected)
    try:
        await c.read_gatt_char(REGISTER)
    except Exception:
        print("pairen...")
        await c.pair()
        await asyncio.sleep(1.0)

    def on_push(_c, dd: bytearray) -> None:
        d = bytes(dd)
        idp = (d[0], d[1]) if len(d) >= 2 else (None, None)
        print(f"  155e push {d.hex(' ')}  id={{0x{d[0]:02x},0x{d[1]:02x}}}  {parse(idp, d)}")

    await c.start_notify(NOTIFIER, on_push)
    await asyncio.sleep(0.5)

    print("=== bekende registers ===")
    for (i0, i1), name in KNOWN.items():
        try:
            v = await read_reg(c, i0, i1)
            print(f"{name:22s} {{0x{i0:02x},0x{i1:02x}}}: {v.hex(' ')}  -> {parse((i0, i1), v)}")
        except Exception as e:
            print(f"{name} fout: {type(e).__name__}")

    if hunt:
        print("=== accu-hunt: zoek 0x55 (85%) / 0x60 (96%) ===")
        ids = (
            [(0x04, x) for x in range(0x00, 0x11)]
            + [(0x00, x) for x in range(0x00, 0x09)]
            + [(0x02, 0x50), (0x02, 0x04), (0x02, 0x05), (0x02, 0x06)]
        )
        for i0, i1 in ids:
            try:
                v = await read_reg(c, i0, i1)
                p = parse((i0, i1), v)
                flag = "   <=== ACCU?" if "accu" in p else ""
                print(f"{{0x{i0:02x},0x{i1:02x}}}: {v.hex(' ')}{flag}")
            except Exception as e:
                print(f"{{0x{i0:02x},0x{i1:02x}}} fout: {type(e).__name__}")

    print("=== luisteren 3s ===")
    await asyncio.sleep(3.0)
    try:
        await c.disconnect()
    except Exception:
        pass


if __name__ == "__main__":
    asyncio.run(main())
