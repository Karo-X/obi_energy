"""DataUpdateCoordinator for the OBI Energy integration."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ObiApiClient, ObiApiError, ObiAuthError, ObiNotFoundError
from .const import DOMAIN, MEASURE_ENERGY, MEASURE_NEGATIVE_ENERGY

_LOGGER = logging.getLogger(__name__)


@dataclass
class ObiEnergyData:
    """Snapshot of the latest data fetched from the OBI API."""

    sensor_info: dict[str, Any] | None
    energy: dict[str, Any] | None
    negative_energy: dict[str, Any] | None
    bridges_available: bool


def _latest_measurement(
    records: list[dict[str, Any]], measure: str
) -> dict[str, Any] | None:
    """Return the most recent record for the given measure, if any."""
    matching = [
        record
        for record in records
        if record.get("measure") == measure and record.get("value") is not None
    ]
    if not matching:
        return None
    return max(matching, key=lambda record: record.get("timestamp") or "")


class ObiEnergyCoordinator(DataUpdateCoordinator[ObiEnergyData]):
    """Coordinator that polls the OBI API for bridge status and measurements."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: ObiApiClient,
        hh_id: str,
        mid_id: str,
        update_interval: int,
        historical_duration: str,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(seconds=update_interval),
        )
        self.client = client
        self.hh_id = hh_id
        self.mid_id = mid_id
        self.historical_duration = historical_duration

    async def _async_update_data(self) -> ObiEnergyData:
        """Fetch the latest bridge status and historical measurements."""
        sensor_info: dict[str, Any] | None = None
        bridges_available = True

        try:
            bridges = await self.client.async_get_bridges()
        except ObiAuthError as err:
            raise ConfigEntryAuthFailed("OBI authentication failed") from err
        except ObiNotFoundError:
            bridges_available = False
            bridges = []
        except ObiApiError as err:
            raise UpdateFailed(str(err)) from err

        for bridge in bridges:
            if bridge.get("id") != self.hh_id:
                continue
            for sensor in bridge.get("sensors", []):
                if sensor.get("id") == self.mid_id:
                    sensor_info = sensor
                    break

        try:
            historical = await self.client.async_get_historical_data(
                self.hh_id, self.mid_id, self.historical_duration
            )
        except ObiAuthError as err:
            raise ConfigEntryAuthFailed("OBI authentication failed") from err
        except ObiApiError as err:
            raise UpdateFailed(str(err)) from err

        energy = _latest_measurement(historical, MEASURE_ENERGY)
        negative_energy = _latest_measurement(historical, MEASURE_NEGATIVE_ENERGY)

        _LOGGER.debug(
            "Historical data poll: %d record(s) returned; latest energy=%s "
            "(value=%s); latest negative_energy=%s (value=%s)",
            len(historical),
            energy.get("timestamp") if energy else None,
            energy.get("value") if energy else None,
            negative_energy.get("timestamp") if negative_energy else None,
            negative_energy.get("value") if negative_energy else None,
        )

        return ObiEnergyData(
            sensor_info=sensor_info,
            energy=energy,
            negative_energy=negative_energy,
            bridges_available=bridges_available,
        )
