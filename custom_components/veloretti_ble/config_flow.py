"""Config flow for the Veloretti BLE integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS

from .const import BLE_LOCAL_NAME_PREFIX, DOMAIN, METRICS_SERVICE_UUID


def _is_veloretti(info: BluetoothServiceInfoBleak) -> bool:
    """Return True if a discovered device looks like a Veloretti bike."""
    name = (info.name or "").upper()
    if name.startswith(BLE_LOCAL_NAME_PREFIX):
        return True
    return METRICS_SERVICE_UUID in info.service_uuids


def _title(info: BluetoothServiceInfoBleak) -> str:
    """Human-friendly title for a bike."""
    return info.name or f"Veloretti {info.address}"


class VelorettiConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Veloretti BLE."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, BluetoothServiceInfoBleak] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a bike discovered over Bluetooth."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovery_info = discovery_info
        self.context["title_placeholders"] = {"name": _title(discovery_info)}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm setup of a discovered bike."""
        assert self._discovery_info is not None
        info = self._discovery_info
        if user_input is not None:
            return self.async_create_entry(
                title=_title(info), data={CONF_ADDRESS: info.address}
            )
        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": _title(info)},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick a bike from the discovered devices."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            info = self._discovered_devices[address]
            return self.async_create_entry(
                title=_title(info), data={CONF_ADDRESS: info.address}
            )

        current_addresses = self._async_current_ids()
        for info in async_discovered_service_info(self.hass, connectable=True):
            address = info.address
            if address in current_addresses or address in self._discovered_devices:
                continue
            if _is_veloretti(info):
                self._discovered_devices[address] = info

        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(
                        {
                            address: f"{_title(info)} ({address})"
                            for address, info in self._discovered_devices.items()
                        }
                    )
                }
            ),
        )
