"""Active-Bluetooth coordinator for the Veloretti BLE integration.

The bike sleeps most of the time. This coordinator uses Home Assistant's
active-bluetooth coordinator, which only fires a poll while the bike is actually
advertising (awake and in range). When the bike sleeps there are simply no
advertisements, so no poll runs and nothing errors — the entities just go
unavailable until it wakes up again.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    close_stale_connections_by_address,
    establish_connection,
)
from homeassistant.components.bluetooth import (
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
)
from homeassistant.components.bluetooth.active_update_coordinator import (
    ActiveBluetoothDataUpdateCoordinator,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CoreState, HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .comodule import (
    REG_BATTERY,
    ComoduleAuthError,
    ComoduleClient,
    ComoduleData,
    apply_notification,
)
from .const import (
    DEFAULT_POLL_INTERVAL_SECONDS,
    KEEPALIVE_SECONDS,
    METRICS_NOTIFIER_UUID,
)

_LOGGER = logging.getLogger(__name__)

type VelorettiConfigEntry = ConfigEntry[VelorettiCoordinator]


class VelorettiCoordinator(ActiveBluetoothDataUpdateCoordinator[ComoduleData]):
    """Polls a Veloretti bike whenever it is awake and advertising."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: VelorettiConfigEntry,
        address: str,
    ) -> None:
        """Initialize the coordinator."""
        self._entry = entry
        self._comodule = ComoduleClient()
        # Wall-clock time of the last poll that actually read something.
        self.last_successful_poll: datetime | None = None
        # True while we hold a live streaming connection to the bike.
        self._streaming = False
        super().__init__(
            hass=hass,
            logger=_LOGGER,
            address=address,
            needs_poll_method=self._needs_poll,
            poll_method=self._async_poll_bike,
            mode=BluetoothScanningMode.ACTIVE,
            connectable=True,
        )
        # `self.data` is only set by a successful poll; seed it so entities have
        # something to read (all-None) before the first poll completes.
        self.data = ComoduleData()

    @property
    def entry(self) -> VelorettiConfigEntry:
        """Return the config entry this coordinator belongs to."""
        return self._entry

    @property
    def streaming(self) -> bool:
        """Return True while a live connection to the bike is held.

        A connected BLE peripheral often stops advertising, which would make the
        advertisement-based ``available`` flip to False. Entities treat streaming
        as "reachable" so they stay available (and update) while connected.
        """
        return self._streaming

    @callback
    def _needs_poll(
        self,
        service_info: BluetoothServiceInfoBleak,
        seconds_since_last_poll: float | None,
    ) -> bool:
        """Decide whether to poll on this advertisement."""
        return (
            self.hass.state is CoreState.running
            and (
                seconds_since_last_poll is None
                or seconds_since_last_poll >= DEFAULT_POLL_INTERVAL_SECONDS
            )
            and async_ble_device_from_address(
                self.hass, service_info.device.address, connectable=True
            )
            is not None
        )

    async def _async_poll_bike(
        self, service_info: BluetoothServiceInfoBleak
    ) -> ComoduleData:
        """Connect, read a snapshot, then stay connected briefly to stream changes."""
        ble_device: BLEDevice | None = async_ble_device_from_address(
            self.hass, service_info.device.address, connectable=True
        )
        if ble_device is None:
            # Went back to sleep between advertisement and poll; keep last values.
            return self.data

        # Clear any half-open connection left over from a previous poll first.
        await close_stale_connections_by_address(service_info.device.address)
        client = await establish_connection(
            BleakClientWithServiceCache, ble_device, service_info.device.address
        )
        try:
            # The Metrics/Security characteristics require a bond. On BlueZ this
            # is a best-effort "Just Works" pairing; ignore if already bonded or
            # unsupported on the adapter/proxy.
            try:
                await client.pair()
            except Exception as err:  # noqa: BLE001 - adapters/proxies vary
                _LOGGER.debug("pair() skipped: %s", err)
            # Snapshot: authenticate + read every register once, publish it.
            self._publish(await self._comodule.async_poll(client))
            # Then stay connected and stream change-pushes on the notifier, so
            # assist/light/speed changes appear in near real-time instead of only
            # on the next reconnect.
            await self._async_listen(client)
        except ComoduleAuthError as err:
            _LOGGER.warning("Authentication with the bike failed: %s", err)
        except BleakError as err:
            _LOGGER.debug("connection error during poll/listen: %s", err)
        finally:
            try:
                await client.disconnect()
            except Exception as err:  # noqa: BLE001 - a disconnect hiccup must
                # not discard the reading we already published
                _LOGGER.debug("disconnect failed: %s", err)
        return self.data

    @callback
    def _publish(self, data: ComoduleData) -> None:
        """Backfill last-known values, stamp last-seen, and publish the snapshot."""
        # Only stamp "last seen" when the module actually answered a register, so
        # a connection that authed but read nothing doesn't move the timestamp.
        if data.has_any():
            self.last_successful_poll = dt_util.utcnow()

        # If a register didn't answer this cycle, keep the last known value instead
        # of blanking the sensor (a value of 0 is a real read, not None).
        prev = self.data
        if data.battery_soc is None:
            data.battery_soc = prev.battery_soc
        if data.assist_level is None:
            data.assist_level = prev.assist_level
        if data.lights is None:
            # lights rides in the same {00,C0} packet as assist; keep it in sync.
            data.lights = prev.lights
        if data.speed_kmh is None:
            data.speed_kmh = prev.speed_kmh
        if data.motion_raw is None:
            data.motion_raw = prev.motion_raw
        self.data = data
        self.async_update_listeners()

    @callback
    def _set_streaming(self, value: bool) -> None:
        """Flip the streaming flag and let entities re-evaluate availability."""
        if self._streaming != value:
            self._streaming = value
            self.async_update_listeners()

    async def _async_listen(self, client: BleakClientWithServiceCache) -> None:
        """Stay connected and stream change-pushes until the bike drops off.

        The module pushes a register the moment its value changes, so assist,
        light and speed changes appear immediately for as long as the bike is on.
        A periodic battery read keeps the link verified (and the battery fresh)
        while nothing is changing, and ends the session if the connection died.
        """

        @callback
        def _on_push(_char: object, raw: bytearray) -> None:
            if apply_notification(self.data, bytes(raw)):
                self.last_successful_poll = dt_util.utcnow()
                self.async_update_listeners()

        try:
            await client.start_notify(METRICS_NOTIFIER_UUID, _on_push)
        except BleakError as err:
            _LOGGER.debug("could not subscribe to the notifier: %s", err)
            return

        self._set_streaming(True)
        try:
            while client.is_connected and self.hass.state is CoreState.running:
                await asyncio.sleep(KEEPALIVE_SECONDS)
                if not client.is_connected:
                    break
                try:
                    packet = await self._comodule.async_read_register(
                        client, REG_BATTERY
                    )
                except BleakError as err:
                    _LOGGER.debug("keepalive read failed, ending session: %s", err)
                    break
                if packet is not None and apply_notification(self.data, packet):
                    self.last_successful_poll = dt_util.utcnow()
                    self.async_update_listeners()
        finally:
            self._set_streaming(False)
            try:
                await client.stop_notify(METRICS_NOTIFIER_UUID)
            except Exception:  # noqa: BLE001 - fine if we're already disconnecting
                pass
