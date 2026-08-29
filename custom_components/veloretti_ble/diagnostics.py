"""Diagnostics support for the Veloretti BLE integration.

The raw register packets exposed here are what someone mapping a different
Comodule bike model actually needs: attaching a diagnostics download to an issue
is enough to work out where that firmware generation keeps battery, assist and
the rest, without asking the reporter to read log files.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .coordinator import VelorettiConfigEntry

# The MAC address identifies one specific bike, and the entry title usually
# carries its owner's name. Neither is needed to decode a register map.
TO_REDACT = {"address", "unique_id", "title"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: VelorettiConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    last_poll = coordinator.last_successful_poll
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
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
