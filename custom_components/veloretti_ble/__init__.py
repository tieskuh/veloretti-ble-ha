"""The Veloretti BLE integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from .const import PRESENCE_CHECK_SECONDS
from .coordinator import VelorettiConfigEntry, VelorettiCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: VelorettiConfigEntry) -> bool:
    """Set up Veloretti BLE from a config entry."""
    address: str = entry.data[CONF_ADDRESS]

    coordinator = VelorettiCoordinator(hass, entry, address)
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Start listening for advertisements; polling happens automatically while the
    # bike is awake. Nothing happens (and nothing errors) while it sleeps.
    entry.async_on_unload(coordinator.async_start())
    # Advertisements alone are not enough to notice an awake bike (see
    # `async_check_presence`), so also look for it on a timer.
    entry.async_on_unload(
        async_track_time_interval(
            hass,
            coordinator.async_check_presence,
            timedelta(seconds=PRESENCE_CHECK_SECONDS),
        )
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: VelorettiConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
