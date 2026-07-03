"""Sensor platform for the OBI Energy integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, WH_PER_KWH
from .coordinator import ObiEnergyCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up OBI Energy sensors from a config entry."""
    coordinator: ObiEnergyCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        [
            ObiEnergySensor(coordinator, entry),
            ObiEnergyKwhSensor(coordinator, entry),
            ObiNegativeEnergySensor(coordinator, entry),
            ObiEinspeisungKwhSensor(coordinator, entry),
            ObiNettoEnergyKwhSensor(coordinator, entry),
            ObiLivePowerSensor(coordinator, entry),
            ObiLiveRssiSensor(coordinator, entry),
            ObiLiveBatterySensor(coordinator, entry),
            ObiLiveLastMessageSensor(coordinator, entry),
            ObiBridgeBatterySensor(coordinator, entry),
            ObiBridgeConnectionStrengthSensor(coordinator, entry),
            ObiLastRecordReceivedSensor(coordinator, entry),
        ]
    )


class ObiEnergyBaseEntity(CoordinatorEntity[ObiEnergyCoordinator], SensorEntity):
    """Common base for all OBI Energy sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ObiEnergyCoordinator,
        entry: ConfigEntry,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        # Pin the entity_id (e.g. sensor.obi_energy) so it stays stable and
        # matches the documented names regardless of the translated name.
        self._attr_suggested_object_id = f"obi_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.hh_id}_{coordinator.mid_id}")},
            name="OBI Energy Bridge",
            manufacturer="OBI",
            model="heyOBI Energy Tracking",
        )


class ObiEnergySensor(ObiEnergyBaseEntity):
    """Cumulative energy consumption in Wh."""

    def __init__(self, coordinator: ObiEnergyCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
            SensorEntityDescription(
                key="energy",
                translation_key="energy",
                native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
                device_class=SensorDeviceClass.ENERGY,
                state_class=SensorStateClass.TOTAL_INCREASING,
            ),
        )

    @property
    def available(self) -> bool:
        """Return True if the last energy measurement is known."""
        return super().available and self.coordinator.data.energy is not None

    @property
    def native_value(self) -> float | None:
        """Return the latest cumulative energy value in Wh."""
        energy = self.coordinator.data.energy
        return energy["value"] if energy else None


class ObiEnergyKwhSensor(ObiEnergyBaseEntity):
    """Cumulative energy consumption in kWh."""

    def __init__(self, coordinator: ObiEnergyCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
            SensorEntityDescription(
                key="energy_kwh",
                translation_key="energy_kwh",
                native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                device_class=SensorDeviceClass.ENERGY,
                state_class=SensorStateClass.TOTAL_INCREASING,
                suggested_display_precision=2,
            ),
        )

    @property
    def available(self) -> bool:
        """Return True if the last energy measurement is known."""
        return super().available and self.coordinator.data.energy is not None

    @property
    def native_value(self) -> float | None:
        """Return the latest cumulative energy value in kWh."""
        energy = self.coordinator.data.energy
        return energy["value"] / WH_PER_KWH if energy else None


class ObiNegativeEnergySensor(ObiEnergyBaseEntity):
    """Cumulative feed-in (negative energy) in Wh."""

    def __init__(self, coordinator: ObiEnergyCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
            SensorEntityDescription(
                key="negative_energy",
                translation_key="negative_energy",
                native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
                device_class=SensorDeviceClass.ENERGY,
                state_class=SensorStateClass.TOTAL_INCREASING,
            ),
        )

    @property
    def available(self) -> bool:
        """Return True if the last feed-in measurement is known."""
        return super().available and self.coordinator.data.negative_energy is not None

    @property
    def native_value(self) -> float | None:
        """Return the latest cumulative feed-in value in Wh."""
        negative_energy = self.coordinator.data.negative_energy
        return negative_energy["value"] if negative_energy else None


class ObiEinspeisungKwhSensor(ObiEnergyBaseEntity):
    """Cumulative feed-in (Einspeisung) in kWh."""

    def __init__(self, coordinator: ObiEnergyCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
            SensorEntityDescription(
                key="einspeisung_kwh",
                translation_key="einspeisung_kwh",
                native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                device_class=SensorDeviceClass.ENERGY,
                state_class=SensorStateClass.TOTAL_INCREASING,
                suggested_display_precision=2,
            ),
        )

    @property
    def available(self) -> bool:
        """Return True if the last feed-in measurement is known."""
        return super().available and self.coordinator.data.negative_energy is not None

    @property
    def native_value(self) -> float | None:
        """Return the latest cumulative feed-in value in kWh."""
        negative_energy = self.coordinator.data.negative_energy
        return negative_energy["value"] / WH_PER_KWH if negative_energy else None


class ObiNettoEnergyKwhSensor(ObiEnergyBaseEntity):
    """Net energy (consumption minus feed-in) in kWh. Can be negative."""

    def __init__(self, coordinator: ObiEnergyCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
            SensorEntityDescription(
                key="netto_energy_kwh",
                translation_key="netto_energy_kwh",
                native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                device_class=SensorDeviceClass.ENERGY,
                state_class=SensorStateClass.TOTAL,
                suggested_display_precision=2,
            ),
        )

    @property
    def available(self) -> bool:
        """Return True only when both measurements are known."""
        data = self.coordinator.data
        return (
            super().available
            and data.energy is not None
            and data.negative_energy is not None
        )

    @property
    def native_value(self) -> float | None:
        """Return consumption minus feed-in, in kWh."""
        data = self.coordinator.data
        if data.energy is None or data.negative_energy is None:
            return None
        return (data.energy["value"] - data.negative_energy["value"]) / WH_PER_KWH


class ObiLivePowerSensor(ObiEnergyBaseEntity):
    """Current live power in W."""

    def __init__(self, coordinator: ObiEnergyCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
            SensorEntityDescription(
                key="live_power",
                translation_key="live_power",
                native_unit_of_measurement=UnitOfPower.WATT,
                device_class=SensorDeviceClass.POWER,
                state_class=SensorStateClass.MEASUREMENT,
            ),
        )

    @property
    def available(self) -> bool:
        """Return True once a live power reading has arrived."""
        return super().available and self.coordinator.data.live_power is not None

    @property
    def native_value(self) -> int | float | None:
        """Return the latest live power value."""
        return self.coordinator.data.live_power

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose live-stream diagnostics."""
        data = self.coordinator.data
        return {
            "live_connected": data.live_connected,
            "live_last_error": data.live_last_error,
            "live_last_message_at": data.live_last_message_at,
        }


class ObiLiveRssiSensor(ObiEnergyBaseEntity):
    """Live RSSI from the bridge sensor."""

    def __init__(self, coordinator: ObiEnergyCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
            SensorEntityDescription(
                key="live_rssi",
                translation_key="live_rssi",
                native_unit_of_measurement="dBm",
                device_class=SensorDeviceClass.SIGNAL_STRENGTH,
                state_class=SensorStateClass.MEASUREMENT,
                entity_category=EntityCategory.DIAGNOSTIC,
            ),
        )

    @property
    def available(self) -> bool:
        """Return True once a live RSSI reading has arrived."""
        return super().available and self.coordinator.data.live_rssi is not None

    @property
    def native_value(self) -> int | None:
        """Return the latest live RSSI value."""
        return self.coordinator.data.live_rssi


class ObiLiveBatterySensor(ObiEnergyBaseEntity):
    """Live battery level from the bridge sensor."""

    def __init__(self, coordinator: ObiEnergyCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
            SensorEntityDescription(
                key="live_battery",
                translation_key="live_battery",
                native_unit_of_measurement=PERCENTAGE,
                device_class=SensorDeviceClass.BATTERY,
                state_class=SensorStateClass.MEASUREMENT,
                entity_category=EntityCategory.DIAGNOSTIC,
            ),
        )

    @property
    def available(self) -> bool:
        """Return True once a live battery reading has arrived."""
        return super().available and self.coordinator.data.live_battery is not None

    @property
    def native_value(self) -> int | None:
        """Return the latest live battery value."""
        return self.coordinator.data.live_battery


class ObiLiveLastMessageSensor(ObiEnergyBaseEntity):
    """Timestamp of the last live WebSocket message."""

    def __init__(self, coordinator: ObiEnergyCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
            SensorEntityDescription(
                key="live_last_message",
                translation_key="live_last_message",
                device_class=SensorDeviceClass.TIMESTAMP,
                entity_category=EntityCategory.DIAGNOSTIC,
            ),
        )

    @property
    def available(self) -> bool:
        """Return True once a live message has arrived."""
        return (
            super().available
            and self.coordinator.data.live_last_message_at is not None
        )

    @property
    def native_value(self):
        """Return the last live message timestamp as a datetime."""
        return self.coordinator.data.live_last_message_at


class ObiBridgeBatterySensor(ObiEnergyBaseEntity):
    """Battery level of the OBI bridge sensor."""

    def __init__(self, coordinator: ObiEnergyCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
            SensorEntityDescription(
                key="bridge_battery",
                translation_key="bridge_battery",
                native_unit_of_measurement=PERCENTAGE,
                device_class=SensorDeviceClass.BATTERY,
                entity_category=EntityCategory.DIAGNOSTIC,
            ),
        )

    @property
    def available(self) -> bool:
        """Return True if bridge/sensor info is known."""
        return super().available and self.coordinator.data.sensor_info is not None

    @property
    def native_value(self) -> int | None:
        """Return the battery level percentage."""
        sensor_info = self.coordinator.data.sensor_info
        return sensor_info.get("batteryLevel") if sensor_info else None


class ObiBridgeConnectionStrengthSensor(ObiEnergyBaseEntity):
    """Textual connection strength of the OBI bridge sensor."""

    def __init__(self, coordinator: ObiEnergyCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
            SensorEntityDescription(
                key="bridge_connection_strength",
                translation_key="bridge_connection_strength",
                icon="mdi:transmission-tower",
                entity_category=EntityCategory.DIAGNOSTIC,
            ),
        )

    @property
    def available(self) -> bool:
        """Return True if bridge/sensor info is known."""
        return super().available and self.coordinator.data.sensor_info is not None

    @property
    def native_value(self) -> str | None:
        """Return the connection strength, e.g. GOOD_CONNECTION."""
        sensor_info = self.coordinator.data.sensor_info
        return sensor_info.get("connectionStrength") if sensor_info else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose non-sensitive diagnostic identifiers as attributes.

        Never includes the JWT or credentials.
        """
        sensor_info = self.coordinator.data.sensor_info or {}
        return {
            "hh_id": self.coordinator.hh_id,
            "mid_id": self.coordinator.mid_id,
            "upload_interval": sensor_info.get("uploadInterval"),
            "firmware_version": sensor_info.get("firmwareVersion"),
            "hardware_version": sensor_info.get("hardwareVersion"),
        }


class ObiLastRecordReceivedSensor(ObiEnergyBaseEntity):
    """Timestamp of the last record received from the bridge sensor."""

    def __init__(self, coordinator: ObiEnergyCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
            SensorEntityDescription(
                key="last_record_received",
                translation_key="last_record_received",
                device_class=SensorDeviceClass.TIMESTAMP,
                entity_category=EntityCategory.DIAGNOSTIC,
            ),
        )

    @property
    def available(self) -> bool:
        """Return True if a last-received timestamp is known."""
        sensor_info = self.coordinator.data.sensor_info
        return (
            super().available
            and sensor_info is not None
            and sensor_info.get("lastRecordReceivedAt") is not None
        )

    @property
    def native_value(self):
        """Return the last-received timestamp as a datetime."""
        sensor_info = self.coordinator.data.sensor_info
        if not sensor_info:
            return None
        raw = sensor_info.get("lastRecordReceivedAt")
        if not raw:
            return None
        return dt_util.parse_datetime(raw)
