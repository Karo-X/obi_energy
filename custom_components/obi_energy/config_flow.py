"""Config flow for the OBI Energy integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, CONF_SCAN_INTERVAL
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ObiApiClient, ObiAuthError, ObiConnectionError, ObiNotFoundError
from .const import (
    CONF_DEBUG,
    CONF_HH_ID,
    CONF_HISTORICAL_DURATION,
    CONF_LOGIN_REFRESH_INTERVAL,
    CONF_MID_ID,
    DEFAULT_DEBUG,
    DEFAULT_HISTORICAL_DURATION,
    DEFAULT_LOGIN_REFRESH_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

STEP_MANUAL_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HH_ID): str,
        vol.Required(CONF_MID_ID): str,
    }
)


def _flatten_bridges(bridges: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    """Flatten the /bridges response into (hh_id, mid_id, label) tuples."""
    pairs: list[tuple[str, str, str]] = []
    for bridge in bridges:
        hh_id = bridge.get("id")
        if not hh_id:
            continue
        for sensor in bridge.get("sensors", []):
            mid_id = sensor.get("id")
            if not mid_id:
                continue
            strength = sensor.get("connectionStrength", "")
            battery = sensor.get("batteryLevel", "")
            label = f"{hh_id} / {mid_id} ({strength}, {battery}%)"
            pairs.append((hh_id, mid_id, label))
    return pairs


class ObiEnergyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for OBI Energy."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._email: str | None = None
        self._password: str | None = None
        self._client: ObiApiClient | None = None
        self._pairs: list[tuple[str, str, str]] = []
        self._reauth_entry: config_entries.ConfigEntry | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step: ask for OBI email and password."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._email = user_input[CONF_EMAIL]
            self._password = user_input[CONF_PASSWORD]

            session = async_get_clientsession(self.hass)
            client = ObiApiClient(
                session, self._email, self._password, DEFAULT_LOGIN_REFRESH_INTERVAL
            )

            try:
                await client.async_login()
            except ObiAuthError as err:
                _LOGGER.warning("OBI login rejected during config flow: %s", err)
                errors["base"] = "invalid_auth"
            except ObiConnectionError:
                _LOGGER.exception("OBI connection failed during config flow (login)")
                errors["base"] = "cannot_connect"
            else:
                self._client = client
                try:
                    bridges = await client.async_get_bridges()
                except ObiNotFoundError as err:
                    _LOGGER.info(
                        "OBI /bridges not found, falling back to manual entry: %s", err
                    )
                    return await self.async_step_manual()
                except ObiConnectionError:
                    _LOGGER.exception(
                        "OBI connection failed during config flow (bridges)"
                    )
                    errors["base"] = "cannot_connect"
                else:
                    pairs = _flatten_bridges(bridges)
                    if not pairs:
                        return await self.async_step_manual()
                    if len(pairs) == 1:
                        hh_id, mid_id, _label = pairs[0]
                        return await self._async_create_entry(hh_id, mid_id)
                    self._pairs = pairs
                    return await self.async_step_select_bridge()

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_select_bridge(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Let the user pick a bridge/sensor when multiple are found."""
        errors: dict[str, str] = {}
        choices = {f"{hh_id}|{mid_id}": label for hh_id, mid_id, label in self._pairs}

        if user_input is not None:
            hh_id, mid_id = user_input["bridge"].split("|", 1)
            return await self._async_create_entry(hh_id, mid_id)

        schema = vol.Schema({vol.Required("bridge"): vol.In(choices)})
        return self.async_show_form(
            step_id="select_bridge", data_schema=schema, errors=errors
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Ask for HH_ID/MID_ID manually when /bridges is unavailable or empty."""
        errors: dict[str, str] = {}

        if user_input is not None:
            hh_id = user_input[CONF_HH_ID]
            mid_id = user_input[CONF_MID_ID]

            try:
                await self._client.async_get_historical_data(
                    hh_id, mid_id, DEFAULT_HISTORICAL_DURATION
                )
            except ObiNotFoundError as err:
                _LOGGER.warning(
                    "OBI historical data not found for manual hh_id/mid_id: %s", err
                )
                errors["base"] = "invalid_ids"
            except ObiConnectionError:
                _LOGGER.exception(
                    "OBI connection failed during config flow (manual validation)"
                )
                errors["base"] = "cannot_connect"
            else:
                return await self._async_create_entry(hh_id, mid_id)

        return self.async_show_form(
            step_id="manual", data_schema=STEP_MANUAL_DATA_SCHEMA, errors=errors
        )

    async def _async_create_entry(
        self, hh_id: str, mid_id: str
    ) -> config_entries.ConfigFlowResult:
        """Create the config entry once email/password/hh_id/mid_id are known."""
        await self.async_set_unique_id(f"{hh_id}_{mid_id}")
        self._abort_if_unique_id_configured()

        data = {
            CONF_EMAIL: self._email,
            CONF_PASSWORD: self._password,
            CONF_HH_ID: hh_id,
            CONF_MID_ID: mid_id,
        }
        return self.async_create_entry(title="OBI Energy", data=data)

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Handle reauthentication triggered by ConfigEntryAuthFailed."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        self._email = entry_data.get(CONF_EMAIL)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Ask for a new password and verify it before updating the entry."""
        errors: dict[str, str] = {}

        if user_input is not None and self._reauth_entry is not None:
            password = user_input[CONF_PASSWORD]
            session = async_get_clientsession(self.hass)
            client = ObiApiClient(
                session, self._email, password, DEFAULT_LOGIN_REFRESH_INTERVAL
            )
            try:
                await client.async_login()
            except ObiAuthError as err:
                _LOGGER.warning("OBI reauth login rejected: %s", err)
                errors["base"] = "invalid_auth"
            except ObiConnectionError:
                _LOGGER.exception("OBI connection failed during reauth confirm")
                errors["base"] = "cannot_connect"
            else:
                new_data = {**self._reauth_entry.data, CONF_PASSWORD: password}
                self.hass.config_entries.async_update_entry(
                    self._reauth_entry, data=new_data
                )
                await self.hass.config_entries.async_reload(
                    self._reauth_entry.entry_id
                )
                return self.async_abort(reason="reauth_successful")

        schema = vol.Schema({vol.Required(CONF_PASSWORD): str})
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=schema,
            errors=errors,
            description_placeholders={"email": self._email or ""},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Allow changing OBI email/password from an existing entry."""
        return await self.async_step_reconfigure_confirm(user_input)

    async def async_step_reconfigure_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Verify and store new credentials for an existing entry."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        errors: dict[str, str] = {}

        if user_input is not None and entry is not None:
            email = user_input[CONF_EMAIL]
            password = user_input[CONF_PASSWORD]
            session = async_get_clientsession(self.hass)
            client = ObiApiClient(
                session, email, password, DEFAULT_LOGIN_REFRESH_INTERVAL
            )
            try:
                await client.async_login()
            except ObiAuthError as err:
                _LOGGER.warning("OBI reconfigure login rejected: %s", err)
                errors["base"] = "invalid_auth"
            except ObiConnectionError:
                _LOGGER.exception("OBI connection failed during reconfigure confirm")
                errors["base"] = "cannot_connect"
            else:
                new_data = {**entry.data, CONF_EMAIL: email, CONF_PASSWORD: password}
                self.hass.config_entries.async_update_entry(entry, data=new_data)
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reconfigure_successful")

        default_email = entry.data.get(CONF_EMAIL, "") if entry is not None else ""
        schema = vol.Schema(
            {
                vol.Required(CONF_EMAIL, default=default_email): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )
        return self.async_show_form(
            step_id="reconfigure_confirm", data_schema=schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> ObiEnergyOptionsFlow:
        """Create the options flow."""
        return ObiEnergyOptionsFlow()


class ObiEnergyOptionsFlow(config_entries.OptionsFlow):
    """Handle OBI Energy options: scan interval, refresh, duration, debug, manual IDs."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
        data = self.config_entry.data
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(min=10)),
                vol.Required(
                    CONF_LOGIN_REFRESH_INTERVAL,
                    default=options.get(
                        CONF_LOGIN_REFRESH_INTERVAL, DEFAULT_LOGIN_REFRESH_INTERVAL
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=60)),
                vol.Required(
                    CONF_HISTORICAL_DURATION,
                    default=options.get(
                        CONF_HISTORICAL_DURATION, DEFAULT_HISTORICAL_DURATION
                    ),
                ): str,
                vol.Required(
                    CONF_DEBUG, default=options.get(CONF_DEBUG, DEFAULT_DEBUG)
                ): bool,
                vol.Optional(
                    CONF_HH_ID,
                    default=options.get(CONF_HH_ID, data.get(CONF_HH_ID, "")),
                ): str,
                vol.Optional(
                    CONF_MID_ID,
                    default=options.get(CONF_MID_ID, data.get(CONF_MID_ID, "")),
                ): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
