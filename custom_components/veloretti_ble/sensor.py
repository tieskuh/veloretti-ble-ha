"""Sensor platform for the Veloretti BLE integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfSpeed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import VelorettiConfigEntry, VelorettiCoordinator
from .entity import VelorettiEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class VelorettiSensorEntityDescription(SensorEntityDescription):
    """Describes a Veloretti sensor."""

    value_fn: Callable[[VelorettiCoordinator], StateType | datetime]
    # Keep reporting the last-known value while the bike is asleep.
    always_available: bool = False
    # Persist the last value across a Home Assistant restart.
    restore: bool = False


SENSORS: tuple[VelorettiSensorEntityDescription, ...] = (
    VelorettiSensorEntityDescription(
        key="battery_soc",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        always_available=True,
        restore=True,
        value_fn=lambda coordinator: coordinator.data.battery_soc,
    ),
    VelorettiSensorEntityDescription(
        key="assist_level",
        translation_key="assist_level",
        icon="mdi:bike-fast",
        # Discrete mode selector (0-4) — no state_class, so the recorder does not
        # compile meaningless mean/min/max long-term statistics for it.
        value_fn=lambda coordinator: coordinator.data.assist_level,
    ),
    VelorettiSensorEntityDescription(
        key="last_successful_poll",
        translation_key="last_successful_poll",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        always_available=True,
        restore=True,
        value_fn=lambda coordinator: coordinator.last_successful_poll,
    ),
    # Speed in km/h — byte 2 of {02,50}, calibrated ~1:1 against a live ride.
    # Only non-zero while the bike is moving (and in range), so disabled by
    # default; enable it if you want it.
    VelorettiSensorEntityDescription(
        key="speed",
        translation_key="speed",
        device_class=SensorDeviceClass.SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=lambda coordinator: coordinator.data.speed_kmh,
    ),
    # Fine wheel-motion signal (raw uint16) — experimental, disabled by default.
    VelorettiSensorEntityDescription(
        key="motion_raw",
        translation_key="motion_raw",
        icon="mdi:rotate-right",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda coordinator: coordinator.data.motion_raw,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VelorettiConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Veloretti sensors from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        VelorettiSensor(coordinator, description) for description in SENSORS
    )


class VelorettiSensor(VelorettiEntity, RestoreSensor):
    """A Veloretti telemetry sensor."""

    entity_description: VelorettiSensorEntityDescription
    _restored_value: StateType | datetime | None = None

    async def async_added_to_hass(self) -> None:
        """Restore the last value when the bike is offline at startup."""
        await super().async_added_to_hass()
        if self.entity_description.restore and (
            last := await self.async_get_last_sensor_data()
        ) is not None:
            # from_dict already rebuilt a datetime for TIMESTAMP sensors.
            self._restored_value = last.native_value

    @property
    def native_value(self) -> StateType | datetime:
        """Return the current value, falling back to the restored one."""
        value = self.entity_description.value_fn(self.coordinator)
        if value is None and self.entity_description.restore:
            return self._restored_value
        return value
