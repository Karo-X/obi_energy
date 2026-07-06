"""DataUpdateCoordinator for the OBI Energy integration."""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ObiApiClient, ObiApiError, ObiAuthError, ObiNotFoundError
from .const import (
    DOMAIN,
    LIVE_UPLOAD_INTERVAL_DISABLED,
    LIVE_UPLOAD_INTERVAL_ENABLED,
    MEASURE_ENERGY,
    MEASURE_NEGATIVE_ENERGY,
)

_LOGGER = logging.getLogger(__name__)

_LIVE_RECONNECT_DELAY = 10
_LIVE_STALE_AFTER = timedelta(seconds=90)
_LIVE_STALE_CHECK_INTERVAL = 15


@dataclass
class ObiEnergyData:
    """Snapshot of the latest data fetched from the OBI API."""

    sensor_info: dict[str, Any] | None
    energy: dict[str, Any] | None
    negative_energy: dict[str, Any] | None
    bridges_available: bool
    live_power: int | float | None = None
    live_rssi: int | None = None
    live_battery: int | None = None
    live_last_message_at: datetime | None = None
    live_connected: bool = False
    live_last_error: str | None = None
    live_stale: bool = False
    live_upload_interval: int | None = None


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
    return max(matching, key=_measurement_time)


def _measurement_time(record: dict[str, Any]) -> str:
    """Return the timestamp field used by OBI historical-data responses."""
    timestamp = record.get("time") or record.get("timestamp")
    return timestamp if isinstance(timestamp, str) else ""


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
        live_enabled: bool,
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
        self.live_enabled = live_enabled
        self.live_upload_interval = (
            LIVE_UPLOAD_INTERVAL_ENABLED
            if live_enabled
            else LIVE_UPLOAD_INTERVAL_DISABLED
        )
        self._live_task: asyncio.Task[None] | None = None
        self._live_stale_task: asyncio.Task[None] | None = None
        self._live_stop: asyncio.Event | None = None

    def _set_live_data(self, data: ObiEnergyData) -> None:
        """Publish live-only data without rescheduling the historical poll."""
        self.data = data
        self.async_update_listeners()

    async def async_start_live_updates(self) -> None:
        """Start listening for live power readings."""
        if self._live_task is not None and not self._live_task.done():
            return
        self._live_stop = asyncio.Event()
        self._live_task = self.hass.async_create_task(
            self._async_live_update_loop(),
            name=f"{DOMAIN}_live_updates",
        )
        self._live_stale_task = self.hass.async_create_task(
            self._async_live_stale_watchdog(),
            name=f"{DOMAIN}_live_stale_watchdog",
        )

    async def async_stop_live_updates(self) -> None:
        """Stop the live-data listener."""
        had_live_task = self._live_task is not None
        if self._live_stop is not None:
            self._live_stop.set()

        for task in (self._live_task, self._live_stale_task):
            if task is None:
                continue
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self._live_task = None
        self._live_stale_task = None
        self._live_stop = None
        if had_live_task:
            await self.async_disable_live_mode()

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
        current_data = self.data

        _LOGGER.debug(
            "Historical data poll: %d record(s) returned; latest energy=%s "
            "(value=%s); latest negative_energy=%s (value=%s)",
            len(historical),
            _measurement_time(energy) if energy else None,
            energy.get("value") if energy else None,
            _measurement_time(negative_energy) if negative_energy else None,
            negative_energy.get("value") if negative_energy else None,
        )

        return ObiEnergyData(
            sensor_info=sensor_info,
            energy=energy,
            negative_energy=negative_energy,
            bridges_available=bridges_available,
            live_power=current_data.live_power if current_data else None,
            live_rssi=current_data.live_rssi if current_data else None,
            live_battery=current_data.live_battery if current_data else None,
            live_last_message_at=current_data.live_last_message_at
            if current_data
            else None,
            live_connected=current_data.live_connected if current_data else False,
            live_last_error=current_data.live_last_error if current_data else None,
            live_stale=current_data.live_stale if current_data else False,
            live_upload_interval=current_data.live_upload_interval
            if current_data
            else None,
        )

    async def _async_live_update_loop(self) -> None:
        """Maintain the live WebSocket connection and publish incoming readings."""
        assert self._live_stop is not None

        while not self._live_stop.is_set():
            try:
                await self._async_enable_live_mode()
                websocket = await self.client.async_connect_live_data(
                    self.hh_id, self.mid_id
                )
                _LOGGER.debug("OBI live WebSocket connected")
                self._set_live_connection_state(connected=True, error=None)
                try:
                    async for msg in websocket:
                        if self._live_stop.is_set():
                            break
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            self._handle_live_message(msg.data)
                        elif msg.type == aiohttp.WSMsgType.BINARY:
                            self._handle_live_message(msg.data.decode("utf-8"))
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            error = str(websocket.exception())
                            _LOGGER.warning("OBI live WebSocket error: %s", error)
                            self._set_live_connection_state(
                                connected=False, error=error
                            )
                            break
                finally:
                    self._set_live_connection_state(connected=False)
                    await websocket.close()
            except ObiAuthError as err:
                _LOGGER.warning("OBI live WebSocket authentication failed: %s", err)
                self._set_live_connection_state(connected=False, error=str(err))
            except ObiApiError as err:
                _LOGGER.warning("OBI live WebSocket connection failed: %s", err)
                self._set_live_connection_state(connected=False, error=str(err))
            except asyncio.CancelledError:
                raise
            except Exception as err:
                _LOGGER.exception("Unexpected error in OBI live WebSocket listener")
                self._set_live_connection_state(connected=False, error=str(err))

            if not self._live_stop.is_set():
                try:
                    await asyncio.wait_for(
                        self._live_stop.wait(), timeout=_LIVE_RECONNECT_DELAY
                    )
                except asyncio.TimeoutError:
                    pass

    def _handle_live_message(self, raw_message: str) -> None:
        """Update coordinator data from a live WebSocket JSON message."""
        handled = False
        decoder = json.JSONDecoder()
        position = 0

        while position < len(raw_message):
            while position < len(raw_message) and raw_message[position].isspace():
                position += 1

            if position >= len(raw_message):
                break

            try:
                message, position = decoder.raw_decode(raw_message, position)
            except ValueError:
                _LOGGER.debug(
                    "Ignoring invalid OBI live WebSocket message: %r", raw_message
                )
                break

            if self._handle_live_json_message(message):
                handled = True

        if not handled:
            _LOGGER.debug("OBI live WebSocket message contained no live reading")

    def _handle_live_json_message(self, message: Any) -> bool:
        """Update coordinator data from one decoded live WebSocket message."""
        if not isinstance(message, dict) or message.get("event") != "mqttMessage":
            return False

        payload = message.get("data")
        if not isinstance(payload, dict):
            return False

        current_data = self.data
        if current_data is None:
            return False

        self._set_live_data(
            replace(
                current_data,
                live_power=payload.get("power", current_data.live_power),
                live_rssi=payload.get("rssi", current_data.live_rssi),
                live_battery=payload.get("battery", current_data.live_battery),
                live_last_message_at=datetime.now(timezone.utc),
                live_last_error=None,
                live_stale=False,
            )
        )
        _LOGGER.debug(
            "OBI live reading received: power=%s rssi=%s battery=%s",
            payload.get("power"),
            payload.get("rssi"),
            payload.get("battery"),
        )
        return True

    def _set_live_connection_state(
        self, *, connected: bool, error: str | None = None
    ) -> None:
        """Store live WebSocket connection state for diagnostics."""
        current_data = self.data
        if current_data is None:
            return

        self._set_live_data(
            replace(
                current_data,
                live_connected=connected,
                live_last_error=error
                if error is not None
                else current_data.live_last_error,
            )
        )

    async def _async_live_stale_watchdog(self) -> None:
        """Mark live data stale when no live readings arrive for a while."""
        assert self._live_stop is not None

        while not self._live_stop.is_set():
            try:
                await asyncio.wait_for(
                    self._live_stop.wait(), timeout=_LIVE_STALE_CHECK_INTERVAL
                )
                continue
            except asyncio.TimeoutError:
                pass

            current_data = self.data
            if (
                current_data is None
                or current_data.live_last_message_at is None
                or current_data.live_stale
            ):
                continue

            if (
                datetime.now(timezone.utc) - current_data.live_last_message_at
                < _LIVE_STALE_AFTER
            ):
                continue

            _LOGGER.debug("OBI live reading is stale; no message received recently")
            self._set_live_data(replace(current_data, live_stale=True))
            try:
                await self._async_enable_live_mode()
            except ObiAuthError as err:
                _LOGGER.warning("OBI live mode activation failed: %s", err)
                self._set_live_connection_state(connected=False, error=str(err))
            except ObiApiError as err:
                _LOGGER.warning("OBI live mode activation failed: %s", err)
                self._set_live_connection_state(connected=False, error=str(err))

    async def _async_enable_live_mode(self) -> None:
        """Ask the OBI backend to make the sensor publish live readings."""
        sensor = await self.client.async_set_sensor_upload_interval(
            self.mid_id, LIVE_UPLOAD_INTERVAL_ENABLED
        )
        upload_interval = sensor.get("uploadInterval")
        _LOGGER.debug(
            "OBI live mode requested: uploadInterval=%s", upload_interval
        )

        current_data = self.data
        if current_data is None:
            return

        self._set_live_data(
            replace(
                current_data,
                sensor_info=sensor,
                live_upload_interval=upload_interval
                if isinstance(upload_interval, int)
                else LIVE_UPLOAD_INTERVAL_ENABLED,
                live_last_error=None,
            )
        )

    async def async_disable_live_mode(self) -> None:
        """Ask the OBI backend to leave live mode and return to normal uploads."""
        try:
            sensor = await self.client.async_set_sensor_upload_interval(
                self.mid_id, LIVE_UPLOAD_INTERVAL_DISABLED
            )
        except ObiAuthError as err:
            _LOGGER.warning("OBI live mode deactivation failed: %s", err)
            self._set_live_connection_state(connected=False, error=str(err))
            return
        except ObiApiError as err:
            _LOGGER.warning("OBI live mode deactivation failed: %s", err)
            self._set_live_connection_state(connected=False, error=str(err))
            return

        upload_interval = sensor.get("uploadInterval")
        _LOGGER.debug(
            "OBI live mode stopped: uploadInterval=%s", upload_interval
        )

        current_data = self.data
        self.live_upload_interval = (
            upload_interval
            if isinstance(upload_interval, int)
            else LIVE_UPLOAD_INTERVAL_DISABLED
        )
        if current_data is None:
            return

        self._set_live_data(
            replace(
                current_data,
                sensor_info=sensor,
                live_connected=False,
                live_upload_interval=self.live_upload_interval,
                live_last_error=None,
                live_stale=True,
            )
        )
