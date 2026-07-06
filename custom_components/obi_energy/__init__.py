"""The OBI Energy integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, CONF_SCAN_INTERVAL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ObiApiClient
from .const import (
    CONF_DEBUG,
    CONF_HH_ID,
    CONF_HISTORICAL_DURATION,
    CONF_LOGIN_REFRESH_INTERVAL,
    CONF_LIVE_ENABLED,
    CONF_MID_ID,
    DEFAULT_DEBUG,
    DEFAULT_HISTORICAL_DURATION,
    DEFAULT_LOGIN_REFRESH_INTERVAL,
    DEFAULT_LIVE_ENABLED,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .coordinator import ObiEnergyCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up OBI Energy from a config entry."""
    options = entry.options

    if options.get(CONF_DEBUG, DEFAULT_DEBUG):
        logging.getLogger(__package__).setLevel(logging.DEBUG)
    else:
        logging.getLogger(__package__).setLevel(logging.NOTSET)

    session = async_get_clientsession(hass)
    login_refresh_interval = options.get(
        CONF_LOGIN_REFRESH_INTERVAL, DEFAULT_LOGIN_REFRESH_INTERVAL
    )
    client = ObiApiClient(
        session,
        entry.data[CONF_EMAIL],
        entry.data[CONF_PASSWORD],
        login_refresh_interval,
    )

    hh_id = options.get(CONF_HH_ID) or entry.data[CONF_HH_ID]
    mid_id = options.get(CONF_MID_ID) or entry.data[CONF_MID_ID]
    scan_interval = options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    historical_duration = options.get(
        CONF_HISTORICAL_DURATION, DEFAULT_HISTORICAL_DURATION
    )
    live_enabled = options.get(CONF_LIVE_ENABLED, DEFAULT_LIVE_ENABLED)

    coordinator = ObiEnergyCoordinator(
        hass,
        entry,
        client,
        hh_id,
        mid_id,
        scan_interval,
        historical_duration,
        live_enabled,
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    if live_enabled:
        await coordinator.async_start_live_updates()
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: ObiEnergyCoordinator | None = hass.data[DOMAIN].get(entry.entry_id)
    if coordinator is not None:
        await coordinator.async_stop_live_updates()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
