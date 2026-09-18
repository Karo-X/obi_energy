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
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower, UnitOfTime
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
            ObiForecastWeeklySensor(coordinator, entry),
            ObiForecastMonthlySensor(coordinator, entry),
            ObiStandbyDailySensor(coordinator, entry),
            ObiStandbyWeeklySensor(coordinator, entry),
            ObiStandbyMonthlySensor(coordinator, entry),
            ObiStandbyYearlySensor(coordinator, entry),
            ObiOtaStatusSensor(coordinator, entry),
            ObiOtaProgressSensor(coordinator, entry),
            ObiUploadIntervalSensor(coordinator, entry),
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
        data = self.coordinator.data
        return (
            super().available
            and data.live_power is not None
            and not data.live_stale
        )

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
            "live_stale": data.live_stale,
            "live_upload_interval": data.live_upload_interval,
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


class ObiForecastWeeklySensor(ObiEnergyBaseEntity):
    """Weekly consumption forecast."""

    def __init__(self, coordinator: ObiEnergyCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
            SensorEntityDescription(
                key="forecast_weekly",
                translation_key="forecast_weekly",
                native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
                device_class=SensorDeviceClass.ENERGY,
                # TOTAL, not MEASUREMENT: Home Assistant rejects MEASUREMENT
                # for device_class ENERGY. TOTAL_INCREASING would be wrong
                # too - a forecast is revised downwards as well, and HA reads
                # a drop under TOTAL_INCREASING as a meter reset. TOTAL keeps
                # long-term statistics working and tolerates falling values.
                state_class=SensorStateClass.TOTAL,
            ),
        )

    @property
    def available(self) -> bool:
        """Return True if a weekly forecast value is known."""
        return (
            super().available
            and self.coordinator.data.consumption_forecast_weekly is not None
        )

    @property
    def native_value(self) -> int | None:
        """Return the weekly consumption forecast in Wh."""
        return self.coordinator.data.consumption_forecast_weekly


class ObiForecastMonthlySensor(ObiEnergyBaseEntity):
    """Monthly consumption forecast."""

    def __init__(self, coordinator: ObiEnergyCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
            SensorEntityDescription(
                key="forecast_monthly",
                translation_key="forecast_monthly",
                native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
                device_class=SensorDeviceClass.ENERGY,
                # TOTAL, not MEASUREMENT: Home Assistant rejects MEASUREMENT
                # for device_class ENERGY. TOTAL_INCREASING would be wrong
                # too - a forecast is revised downwards as well, and HA reads
                # a drop under TOTAL_INCREASING as a meter reset. TOTAL keeps
                # long-term statistics working and tolerates falling values.
                state_class=SensorStateClass.TOTAL,
            ),
        )

    @property
    def available(self) -> bool:
        """Return True if a monthly forecast value is known."""
        return (
            super().available
            and self.coordinator.data.consumption_forecast_monthly is not None
        )

    @property
    def native_value(self) -> int | None:
        """Return the monthly consumption forecast in Wh."""
        return self.coordinator.data.consumption_forecast_monthly


class _ObiStandbySensorBase(ObiEnergyBaseEntity):
    """Common base for standby-power sensors (one per interval)."""

    _standby_field: str

    @property
    def available(self) -> bool:
        """Return True if at least one standby record is known for this interval."""
        records = getattr(self.coordinator.data, self._standby_field)
        return super().available and bool(records)

    @property
    def native_value(self) -> int | None:
        """Return the most recent average standby power value in W."""
        records = getattr(self.coordinator.data, self._standby_field)
        if not records:
            return None
        latest = max(records, key=lambda r: r.get("time", ""))
        return latest.get("value")


class ObiStandbyDailySensor(_ObiStandbySensorBase):
    """Average standby power for the last completed day.

    The API returns this measure in watts (a power value, e.g. 147), not
    watt-hours, despite the "standby consumption" naming used elsewhere.
    """

    _standby_field = "standby_daily"

    def __init__(self, coordinator: ObiEnergyCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
            SensorEntityDescription(
                key="standby_daily",
                translation_key="standby_daily",
                native_unit_of_measurement=UnitOfPower.WATT,
                device_class=SensorDeviceClass.POWER,
                state_class=SensorStateClass.MEASUREMENT,
            ),
        )


class ObiStandbyWeeklySensor(_ObiStandbySensorBase):
    """Average standby power for the last completed week."""

    _standby_field = "standby_weekly"

    def __init__(self, coordinator: ObiEnergyCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
            SensorEntityDescription(
                key="standby_weekly",
                translation_key="standby_weekly",
                native_unit_of_measurement=UnitOfPower.WATT,
                device_class=SensorDeviceClass.POWER,
                state_class=SensorStateClass.MEASUREMENT,
            ),
        )


class ObiStandbyMonthlySensor(_ObiStandbySensorBase):
    """Average standby power for the last completed month."""

    _standby_field = "standby_monthly"

    def __init__(self, coordinator: ObiEnergyCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
            SensorEntityDescription(
                key="standby_monthly",
                translation_key="standby_monthly",
                native_unit_of_measurement=UnitOfPower.WATT,
                device_class=SensorDeviceClass.POWER,
                state_class=SensorStateClass.MEASUREMENT,
            ),
        )


class ObiStandbyYearlySensor(_ObiStandbySensorBase):
    """Average standby power for the last completed year."""

    _standby_field = "standby_yearly"

    def __init__(self, coordinator: ObiEnergyCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
            SensorEntityDescription(
                key="standby_yearly",
                translation_key="standby_yearly",
                native_unit_of_measurement=UnitOfPower.WATT,
                device_class=SensorDeviceClass.POWER,
                state_class=SensorStateClass.MEASUREMENT,
            ),
        )


class ObiOtaStatusSensor(ObiEnergyBaseEntity):
    """OTA update status of the OBI bridge sensor."""

    def __init__(self, coordinator: ObiEnergyCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
            SensorEntityDescription(
                key="ota_status",
                translation_key="ota_status",
                icon="mdi:cloud-download-outline",
                entity_category=EntityCategory.DIAGNOSTIC,
            ),
        )

    @property
    def available(self) -> bool:
        """Return True if bridge/sensor info is known."""
        return super().available and self.coordinator.data.sensor_info is not None

    @property
    def native_value(self) -> str | None:
        """Return the OTA status, e.g. NOT_UPDATING."""
        sensor_info = self.coordinator.data.sensor_info
        return sensor_info.get("otaStatus") if sensor_info else None


class ObiOtaProgressSensor(ObiEnergyBaseEntity):
    """OTA update progress of the OBI bridge sensor."""

    def __init__(self, coordinator: ObiEnergyCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
            SensorEntityDescription(
                key="ota_progress",
                translation_key="ota_progress",
                native_unit_of_measurement=PERCENTAGE,
                state_class=SensorStateClass.MEASUREMENT,
                icon="mdi:cloud-download-outline",
                entity_category=EntityCategory.DIAGNOSTIC,
            ),
        )

    @property
    def available(self) -> bool:
        """Return True if bridge/sensor info is known."""
        return super().available and self.coordinator.data.sensor_info is not None

    @property
    def native_value(self) -> int | None:
        """Return the OTA progress percentage, null outside of an update."""
        sensor_info = self.coordinator.data.sensor_info
        return sensor_info.get("otaProgress") if sensor_info else None


class ObiUploadIntervalSensor(ObiEnergyBaseEntity):
    """Current reporting interval of the OBI bridge sensor."""

    def __init__(self, coordinator: ObiEnergyCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
            SensorEntityDescription(
                key="upload_interval",
                translation_key="upload_interval",
                native_unit_of_measurement=UnitOfTime.SECONDS,
                icon="mdi:timer-outline",
                entity_category=EntityCategory.DIAGNOSTIC,
            ),
        )

    @property
    def available(self) -> bool:
        """Return True if bridge/sensor info is known."""
        return super().available and self.coordinator.data.sensor_info is not None

    @property
    def native_value(self) -> int | None:
        """Return the current reporting interval in seconds."""
        sensor_info = self.coordinator.data.sensor_info
        return sensor_info.get("uploadInterval") if sensor_info else None
