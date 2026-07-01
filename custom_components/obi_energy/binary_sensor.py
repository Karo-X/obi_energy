"""Binary sensor platform for the OBI Energy integration."""
from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ObiEnergyCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the OBI Energy binary sensor from a config entry."""
    coordinator: ObiEnergyCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ObiBridgeOnlineBinarySensor(coordinator, entry)])


class ObiBridgeOnlineBinarySensor(
    CoordinatorEntity[ObiEnergyCoordinator], BinarySensorEntity
):
    """Whether the OBI bridge sensor is currently online."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ObiEnergyCoordinator, entry: ConfigEntry) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self.entity_description = BinarySensorEntityDescription(
            key="bridge_online",
            translation_key="bridge_online",
            device_class=BinarySensorDeviceClass.CONNECTIVITY,
            entity_category=EntityCategory.DIAGNOSTIC,
        )
        self._attr_unique_id = f"{entry.entry_id}_bridge_online"
        # Pin the entity_id to binary_sensor.obi_bridge_online, matching the
        # documented name regardless of the translated entity name.
        self._attr_suggested_object_id = "obi_bridge_online"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.hh_id}_{coordinator.mid_id}")},
            name="OBI Energy Bridge",
            manufacturer="OBI",
            model="heyOBI Energy Tracking",
        )

    @property
    def available(self) -> bool:
        """Return True if bridge/sensor info is known."""
        return super().available and self.coordinator.data.sensor_info is not None

    @property
    def is_on(self) -> bool | None:
        """Return True if the bridge sensor reports itself as online."""
        sensor_info = self.coordinator.data.sensor_info
        return sensor_info.get("isOnline") if sensor_info else None
