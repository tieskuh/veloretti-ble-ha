"""Binary sensor platform for the Veloretti BLE integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import VelorettiConfigEntry, VelorettiCoordinator
from .entity import VelorettiEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class VelorettiBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes a Veloretti binary sensor."""

    value_fn: Callable[[VelorettiCoordinator], bool | None]
    # Keep reporting while the bike is asleep (must be True for connectivity, so
    # it can report "offline" instead of going unavailable itself).
    always_available: bool = False


BINARY_SENSORS: tuple[VelorettiBinarySensorEntityDescription, ...] = (
    VelorettiBinarySensorEntityDescription(
        key="lights",
        translation_key="lights",
        device_class=BinarySensorDeviceClass.LIGHT,
        value_fn=lambda coordinator: coordinator.data.lights,
    ),
    VelorettiBinarySensorEntityDescription(
        key="connectivity",
        translation_key="connectivity",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        # Must never be unavailable, otherwise it could not report "offline".
        always_available=True,
        # On == the bike is currently reachable: advertising, or connected (a
        # connected bike often stops advertising, so check streaming too).
        value_fn=lambda coordinator: coordinator.available or coordinator.streaming,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VelorettiConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Veloretti binary sensors from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        VelorettiBinarySensor(coordinator, description)
        for description in BINARY_SENSORS
    )


class VelorettiBinarySensor(VelorettiEntity, BinarySensorEntity):
    """A Veloretti binary sensor."""

    entity_description: VelorettiBinarySensorEntityDescription

    @property
    def is_on(self) -> bool | None:
        """Return the current state."""
        return self.entity_description.value_fn(self.coordinator)
