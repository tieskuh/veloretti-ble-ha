#!/usr/bin/env python3
"""
capture.py - leg de Comodule notifier-streams (155e + 1581) vast met tijdstempels.

De Metrics Service vereist een BLE-bond: de eerste keer pairt dit script ("Just Works",
geen PIN). Daarna blijft de bond in Windows bewaard.

Usage:
  py proto/capture.py <address> [seconden]      (default 60s)

Tijdens de capture voer je acties uit (wiel draaien, assist wisselen, lader erin);
de tijdstempels koppelen we daarna aan welke bytes veranderen.
"""
import asyncio
import sys
import time

from bleak import BleakClient, BleakScanner

BASE = "-1212-efde-1523-785feabcd123"
NOTIFIER = f"0000155e{BASE}"
REGISTER = f"0000155f{BASE}"
CH1581 = "00001581-0000-1000-8000-00805f9b34fb"


async def find(addr: str):
    for _ in range(5):
        d = await BleakScanner.find_device_by_address(addr, timeout=12)
        if d:
            return d
    return None


async def main() -> None:
    if len(sys.argv) < 2:
        print("usage: capture.py <address> [seconden]")
        return
    addr = sys.argv[1]
    secs = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0

    dev = await find(addr)
    if not dev:
        print("niet gevonden - is de fiets wakker en de app dicht?")
        return
    client = BleakClient(dev, timeout=30)
    await client.connect()
    print("verbonden:", client.is_connected, flush=True)
    try:
        await client.read_gatt_char(REGISTER)  # encryptie afdwingen
    except Exception:
        print("pairen...", flush=True)
        await client.pair()
        await asyncio.sleep(1.0)

    t0 = time.monotonic()

    def make(tag: str):
        def _cb(_c, data: bytearray) -> None:
            print(f"{time.monotonic() - t0:6.1f}s  {tag}: {bytes(data).hex(' ')}", flush=True)
        return _cb

    await client.start_notify(NOTIFIER, make("155e"))
    await client.start_notify(CH1581, make("1581"))
    print(f"--- capturing {secs:.0f}s - voer nu je acties uit ---", flush=True)
    try:
        await asyncio.sleep(secs)
    finally:
        for ch in (NOTIFIER, CH1581):
            try:
                await client.stop_notify(ch)
            except Exception:
                pass
        try:
            await client.disconnect()
        except Exception:
            pass
        print("klaar", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
