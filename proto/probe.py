#!/usr/bin/env python3
"""
probe.py - BLE-recongereedschap voor de Veloretti / Comodule e-bike.

Onderdeel van Fase 0/1 uit het plan. Doel: de bike vinden, het ECHTE MAC-adres
ophalen (de iPhone verbergt dat achter een UUID-handle), de GATT-tabel dumpen en
de Comodule "Metrics Service" live uitlezen om de register-mapping te bevestigen.

Subcommando's:
  scan                       Lijst BLE-adverteerders: naam, adres, RSSI, service-UUIDs.
  dump <adres>               Verbind en dump de volledige GATT-tabel (read-only veilig).
  monitor <adres>            Subscribe op de Metrics-notifier en print updates (hex).
  read <adres> <regid>       Exploratief: selecteer een register en lees de waarde.

Voorbeelden (Windows PowerShell, na 'pip install -r proto\\requirements.txt'):
  py proto\\probe.py scan
  py proto\\probe.py dump E1:23:45:67:89:AB
  py proto\\probe.py monitor E1:23:45:67:89:AB
  py proto\\probe.py read E1:23:45:67:89:AB 0x0201

Let op: er kan maar EEN BLE-client tegelijk verbinden. Sluit de Veloretti-app
(force-quit) voordat je 'dump'/'monitor'/'read' draait, en zet de bike aan.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
from datetime import datetime

from bleak import BleakClient, BleakScanner

# --- Comodule Metrics Service (bron: reverse.bike - te bevestigen op jouw bike) ---
BASE = "-1212-efde-1523-785feabcd123"  # Comodule/Nordic-base UUID-suffix
METRICS_SERVICE = f"00001554{BASE}"
CHAR_REGISTER_ID = f"00001564{BASE}"        # write: selecteer welk register je wilt
CHAR_REGISTER = f"0000155f{BASE}"           # read:  de registerwaarde
CHAR_REGISTER_NOTIFIER = f"0000155e{BASE}"  # notify: pushes bij wijziging

# Bekende register-ID's (Super73; scaling indicatief - Fase 0 valideert deze op de Ace).
KNOWN_REGISTERS = {
    0x0201: "Wielsnelheid (km/h ~ /100)",
    0x0202: "Odometer (km ~ /10)",
    0x0203: "Cadans / Bereik",
    0x0300: "Assist / Walk / Licht / Mode",
    0x0401: "Laadstroom (A ~ /1000)",
}


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def _ascii(raw: bytes) -> str:
    return "".join(chr(b) if 32 <= b < 127 else "." for b in raw)


def _looks_like_bike(name: str | None, service_uuids: list[str]) -> bool:
    lname = (name or "").lower()
    if any(k in lname for k in ("veloretti", "comodule", "ace", "ivy")):
        return True
    return any(u.lower() == METRICS_SERVICE for u in service_uuids)


async def cmd_scan(args: argparse.Namespace) -> None:
    print(f"Scannen ({args.timeout:.0f}s)... zet de bike aan en sluit de Veloretti-app.\n")
    found = await BleakScanner.discover(timeout=args.timeout, return_adv=True)
    rows = [
        (adv.rssi, dev.address, dev.name or adv.local_name or "?", list(adv.service_uuids or []))
        for dev, adv in found.values()
    ]
    rows.sort(key=lambda r: r[0], reverse=True)
    for rssi, address, name, uuids in rows:
        flag = "   <-- mogelijk de bike" if _looks_like_bike(name, uuids) else ""
        print(f"{rssi:>4} dBm  {address}  {name}{flag}")
        for u in uuids:
            tag = "   [METRICS]" if u.lower() == METRICS_SERVICE else ""
            print(f"            service {u}{tag}")
    print(f"\n{len(rows)} apparaten gevonden. Noteer het adres van de bike voor 'dump'/'monitor'.")


async def cmd_dump(args: argparse.Namespace) -> None:
    print(f"Verbinden met {args.address} ...")
    async with BleakClient(args.address, timeout=args.timeout) as client:
        print(f"Verbonden: {client.is_connected}\n")
        metrics_seen = False
        for service in client.services:
            is_metrics = service.uuid.lower() == METRICS_SERVICE
            metrics_seen = metrics_seen or is_metrics
            mark = "   [METRICS SERVICE - match!]" if is_metrics else ""
            print(f"Service {service.uuid}  {service.description}{mark}")
            for char in service.characteristics:
                props = ",".join(char.properties)
                value = ""
                if "read" in char.properties:
                    with contextlib.suppress(Exception):
                        raw = await client.read_gatt_char(char)
                        value = f"  = {raw.hex(' ')}  '{_ascii(raw)}'"
                print(f"  char {char.uuid}  [{props}]{value}")
                for desc in char.descriptors:
                    with contextlib.suppress(Exception):
                        raw = await client.read_gatt_descriptor(desc.handle)
                        print(f"    desc {desc.uuid} = {raw.hex(' ')}")
        print("\nKlaar.", "Metrics Service GEVONDEN - groen licht voor Fase 1." if metrics_seen
              else "Metrics Service NIET gevonden - stuur de output door, dan kijken we naar de fallback.")


async def cmd_monitor(args: argparse.Namespace) -> None:
    def handler(_char, data: bytearray) -> None:
        line = f"{_ts()}  notify  {bytes(data).hex(' ')}"
        if len(data) >= 2:
            reg = int.from_bytes(data[0:2], "little")
            hint = KNOWN_REGISTERS.get(reg, "")
            line += f"   (reg? 0x{reg:04x} {hint})"
        print(line)

    print(f"Verbinden met {args.address} ...")
    async with BleakClient(args.address, timeout=args.timeout) as client:
        print(
            "Verbonden. Subscribe op de Metrics-notifier.\n"
            "Varieer nu de toestand: bike aan/uit, lader erin, achterwiel draaien.\n"
            "Let bij elke verandering op welke register-waarde wijzigt. Ctrl+C om te stoppen.\n"
        )
        await client.start_notify(CHAR_REGISTER_NOTIFIER, handler)
        with contextlib.suppress(asyncio.CancelledError, KeyboardInterrupt):
            while client.is_connected:
                await asyncio.sleep(1)
        with contextlib.suppress(Exception):
            await client.stop_notify(CHAR_REGISTER_NOTIFIER)


async def cmd_read(args: argparse.Namespace) -> None:
    reg = int(args.regid, 0)
    payload = reg.to_bytes(2, "little")  # endianness van de selector te bevestigen in Fase 0
    print(f"Verbinden met {args.address} ...")
    async with BleakClient(args.address, timeout=args.timeout) as client:
        print(f"Register 0x{reg:04x} selecteren via {CHAR_REGISTER_ID} ...")
        await client.write_gatt_char(CHAR_REGISTER_ID, payload, response=True)
        raw = await client.read_gatt_char(CHAR_REGISTER)
        print(f"Waarde ({CHAR_REGISTER}): {raw.hex(' ')}  '{_ascii(raw)}'")
        if len(raw) >= 2:
            print(f"  uint16 LE = {int.from_bytes(raw[0:2], 'little')}"
                  f"   uint16 BE = {int.from_bytes(raw[0:2], 'big')}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="BLE-recon voor de Veloretti/Comodule e-bike.")
    p.add_argument("--timeout", type=float, default=15.0, help="BLE timeout in seconden (default 15).")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("scan", help="Lijst BLE-adverteerders.")
    sp.set_defaults(func=cmd_scan)

    sp = sub.add_parser("dump", help="Dump de GATT-tabel van een adres (read-only veilig).")
    sp.add_argument("address")
    sp.set_defaults(func=cmd_dump)

    sp = sub.add_parser("monitor", help="Subscribe op de Metrics-notifier en print updates.")
    sp.add_argument("address")
    sp.set_defaults(func=cmd_monitor)

    sp = sub.add_parser("read", help="Exploratief: selecteer een register en lees de waarde.")
    sp.add_argument("address")
    sp.add_argument("regid", help="Register-ID, bv. 0x0201")
    sp.set_defaults(func=cmd_read)
    return p


def main() -> None:
    args = build_parser().parse_args()
    try:
        asyncio.run(args.func(args))
    except KeyboardInterrupt:
        print("\nGestopt.")


if __name__ == "__main__":
    main()
