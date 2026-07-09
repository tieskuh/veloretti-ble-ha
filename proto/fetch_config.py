#!/usr/bin/env python3
"""
fetch_config.py - haal de Comodule property-config op (bevat o.a. het accu-register + schaling).

Endpoint (uit de gedecompileerde SDK, A0.java + V7.java):
  GET https://analytics.comodule.com/bleapi/v2/module/{moduleId}/config
        ?stmVersion={int}&bleVersion={str}&type={combinedFirmwareType}&api_key={KEY}

Nodig: de Veloretti api_key (uit de app), de moduleId, en de firmware-versies/type.
(Zonder geldige api_key antwoordt de server met 403 "Failed to authenticate API key".)

Usage:
  py proto/fetch_config.py --api-key KEY --module-id ID --type TYPE [--stm N --ble V]
"""
import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://analytics.comodule.com/bleapi/v2"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--api-key", required=True)
    p.add_argument("--module-id", required=True)
    p.add_argument("--type", required=True, help="combinedFirmwareType")
    p.add_argument("--stm", default="0", help="stmVersion")
    p.add_argument("--ble", default="0", help="bleVersion")
    a = p.parse_args()

    q = urllib.parse.urlencode({
        "stmVersion": a.stm, "bleVersion": a.ble, "type": a.type, "api_key": a.api_key,
    })
    url = f"{BASE}/module/{urllib.parse.quote(a.module_id)}/config?{q}"
    req = urllib.request.Request(url, headers={"User-Agent": "okhttp/4.12.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}")
        sys.exit(1)

    props = data.get("configuration_version_1") or []
    print(f"{len(props)} properties:\n")
    for pr in props:
        ri = pr.get("read_info") or {}
        print(
            f"- {pr.get('identifier')}  [{pr.get('unit_identifier')}]  "
            f"reg={ri.get('registry_id')}  bytes={ri.get('start_byte')}..{ri.get('end_byte')}  "
            f"x{ri.get('value_multiplier')} +{ri.get('value_offset')} signed={ri.get('value_signed')}  "
            f"min={pr.get('min_value')} max={pr.get('max_value')}"
        )

    with open("captures/comodule-config.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print("\nVolledige config opgeslagen: captures/comodule-config.json")


if __name__ == "__main__":
    main()
