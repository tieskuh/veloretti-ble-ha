"""Diagnostics support for the Veloretti BLE integration.

The raw register packets exposed here are what someone mapping a different
Comodule bike model actually needs: attaching a diagnostics download to an issue
is enough to work out where that firmware generation keeps battery, assist and
the rest, without asking the reporter to read log files.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant

from .coordinator import VelorettiConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: VelorettiConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    last_poll = coordinator.last_successful_poll
    return {
        # Deliberately assembled field by field instead of redacting
        # `entry.as_dict()`. That dict identifies the bike in more places than is
        # obvious — the address, the unique id, the title (which carries its
        # owner's name) and, less visibly, the repr of the Bluetooth discovery
        # key — and it gains new fields across Home Assistant versions. Since a
        # diagnostics download is meant to be pasted into a public issue, listing
        # what may go in is the only version-proof way to keep the rest out.
        "entry": {
            "domain": entry.domain,
            "version": entry.version,
            "minor_version": entry.minor_version,
            "source": entry.source,
            "disabled_by": str(entry.disabled_by) if entry.disabled_by else None,
            "pref_disable_polling": entry.pref_disable_polling,
            "options": dict(entry.options),
        },
        "state": {
            # Advertising == the bike is awake and in range.
            "advertising": coordinator.available,
            # Streaming == we hold a live connection and receive notifier pushes.
            "streaming": coordinator.streaming,
            # Auth failed == reachable, but rejecting our handshake.
            "auth_failed": coordinator.auth_failed,
            "last_poll_successful": coordinator.last_poll_successful,
            "last_successful_poll": last_poll.isoformat() if last_poll else None,
        },
        # Decoded telemetry plus every raw register packet seen so far, keyed by
        # register id (e.g. "00c1"), including ones this decoder does not know.
        "data": asdict(coordinator.data),
    }
