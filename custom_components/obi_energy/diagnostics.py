"""Diagnostics support for the OBI Energy integration.

The OBI email, password and JWT are never exposed here. The API client only
ever keeps the token in memory and does not expose it to diagnostics.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import ObiEnergyCoordinator

TO_REDACT = {CONF_EMAIL, CONF_PASSWORD}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: ObiEnergyCoordinator = hass.data[DOMAIN][entry.entry_id]
    data = coordinator.data
    sensor_info = data.sensor_info if data else None

    return {
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "entry_options": dict(entry.options),
        "hh_id": coordinator.hh_id,
        "mid_id": coordinator.mid_id,
        "historical_duration": coordinator.historical_duration,
        "live_options": {
            "enabled": coordinator.live_enabled,
            "upload_interval": coordinator.live_upload_interval,
        },
        "last_update_success": coordinator.last_update_success,
        "bridge_reachable": data.bridges_available if data else None,
        "sensor_info": {
            "uploadInterval": sensor_info.get("uploadInterval") if sensor_info else None,
            "firmwareVersion": sensor_info.get("firmwareVersion") if sensor_info else None,
            "hardwareVersion": sensor_info.get("hardwareVersion") if sensor_info else None,
            "connectionStrength": sensor_info.get("connectionStrength")
            if sensor_info
            else None,
            "batteryLevel": sensor_info.get("batteryLevel") if sensor_info else None,
            "isOnline": sensor_info.get("isOnline") if sensor_info else None,
        },
        "energy": data.energy if data else None,
        "negative_energy": data.negative_energy if data else None,
        "live": {
            "power": data.live_power if data else None,
            "rssi": data.live_rssi if data else None,
            "battery": data.live_battery if data else None,
            "connected": data.live_connected if data else None,
            "last_error": data.live_last_error if data else None,
            "stale": data.live_stale if data else None,
            "upload_interval": data.live_upload_interval if data else None,
            "last_message_at": data.live_last_message_at.isoformat()
            if data and data.live_last_message_at
            else None,
        },
    }
