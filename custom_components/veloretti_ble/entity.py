"""Base entity for the Veloretti BLE integration."""

from __future__ import annotations

from homeassistant.components.bluetooth.passive_update_coordinator import (
    PassiveBluetoothCoordinatorEntity,
)
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity import EntityDescription

from .const import MANUFACTURER
from .coordinator import VelorettiCoordinator


class VelorettiEntity(PassiveBluetoothCoordinatorEntity[VelorettiCoordinator]):
    """Base class for Veloretti entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: VelorettiCoordinator,
        description: EntityDescription,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.entity_description = description
        address = coordinator.address
        self._attr_unique_id = f"{address}_{description.key}"
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, address)},
            manufacturer=MANUFACTURER,
            name=coordinator.entry.title,
        )

    @property
    def available(self) -> bool:
        """Return whether the entity is available.

        By default a Bluetooth coordinator entity is only available while the
        device is advertising. Entities flagged ``always_available`` (battery,
        last-seen, connectivity) must keep showing their last-known value while
        the bike sleeps, so they never go ``unavailable``.
        """
        if getattr(self.entity_description, "always_available", False):
            return True
        return super().available
