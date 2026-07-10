"""Switch platform for the OBI Energy integration."""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
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
    """Set up the OBI Energy switch from a config entry."""
    coordinator: ObiEnergyCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ObiLiveTrackingSwitch(coordinator, entry)])


class ObiLiveTrackingSwitch(CoordinatorEntity[ObiEnergyCoordinator], SwitchEntity):
    """Switch to turn live tracking on/off at runtime.

    This complements the "Enable live tracking" option (which only sets the
    state used when Home Assistant starts): toggling this switch starts or
    stops the live WebSocket immediately, without reloading the integration,
    so it can be driven from automations/schedules.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: ObiEnergyCoordinator, entry: ConfigEntry) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self.entity_description = SwitchEntityDescription(
            key="live_tracking",
            translation_key="live_tracking",
            entity_category=EntityCategory.CONFIG,
        )
        self._attr_unique_id = f"{entry.entry_id}_live_tracking"
        self._attr_suggested_object_id = "obi_live_tracking"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.hh_id}_{coordinator.mid_id}")},
            name="OBI Energy Bridge",
            manufacturer="OBI",
            model="heyOBI Energy Tracking",
        )

    @property
    def is_on(self) -> bool:
        """Return True while live tracking is enabled."""
        return self.coordinator.live_enabled

    async def async_turn_on(self, **kwargs) -> None:
        """Start live tracking."""
        await self.coordinator.async_start_live_updates()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Stop live tracking."""
        await self.coordinator.async_stop_live_updates()
        self.async_write_ha_state()
