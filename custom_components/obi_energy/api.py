"""API client for the OBI / heyOBI Energy Tracking backend.

The JWT obtained on login is only ever kept in memory on this client. It is
never logged, never persisted, and never exposed to entities or attributes.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

from .const import (
    ACCEPT_BRIDGES,
    ACCEPT_HISTORICAL,
    ACCEPT_LANGUAGE,
    API_KEY,
    BRIDGES_URL,
    HISTORICAL_DATA_URL_TEMPLATE,
    LOGIN_COOKIE,
    LOGIN_URL,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 30
_MAX_LOG_BODY_CHARS = 300


class ObiApiError(Exception):
    """Base exception for OBI API errors."""


class ObiAuthError(ObiApiError):
    """Raised when authentication fails (bad credentials or expired session)."""


class ObiConnectionError(ObiApiError):
    """Raised on network or unexpected HTTP errors."""


class ObiNotFoundError(ObiApiError):
    """Raised when a resource (e.g. /bridges) returns 404."""


def _truncate(text: str | None) -> str:
    """Truncate a response body to a safe length for logging."""
    if not text:
        return "<empty body>"
    text = text.strip()
    if len(text) > _MAX_LOG_BODY_CHARS:
        return text[:_MAX_LOG_BODY_CHARS] + "... [truncated]"
    return text


async def _safe_text(resp: aiohttp.ClientResponse) -> str:
    """Best-effort read of a response body for logging. Never raises."""
    try:
        return await resp.text()
    except (aiohttp.ClientError, UnicodeDecodeError):
        return "<could not read body>"


async def _log_http_error(resp: aiohttp.ClientResponse, context: str) -> None:
    """Log the HTTP status and a truncated body. Never logs tokens/passwords."""
    body = await _safe_text(resp)
    _LOGGER.error(
        "%s failed with HTTP %s: %s", context, resp.status, _truncate(body)
    )


class ObiApiClient:
    """Thin async client for the OBI Energy Tracking API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        email: str,
        password: str,
        login_refresh_interval: int,
    ) -> None:
        """Initialize the client. The token is kept only in memory."""
        self._session = session
        self._email = email
        self._password = password
        self._login_refresh_interval = timedelta(seconds=login_refresh_interval)
        self._token: str | None = None
        self._token_obtained_at: datetime | None = None

    def update_credentials(self, email: str, password: str) -> None:
        """Update the credentials used for future logins."""
        self._email = email
        self._password = password
        self._token = None
        self._token_obtained_at = None

    def update_login_refresh_interval(self, login_refresh_interval: int) -> None:
        """Update how often the token is proactively refreshed."""
        self._login_refresh_interval = timedelta(seconds=login_refresh_interval)

    @property
    def is_authenticated(self) -> bool:
        """Return whether a token is currently held in memory."""
        return self._token is not None

    def _token_is_stale(self) -> bool:
        if self._token is None or self._token_obtained_at is None:
            return True
        return datetime.now(timezone.utc) - self._token_obtained_at >= self._login_refresh_interval

    async def async_login(self) -> None:
        """Log in to OBI and store the resulting JWT in memory only."""
        headers = {
            "content-type": "application/json",
            "accept": "*/*",
            "user-agent": USER_AGENT,
            "accept-language": ACCEPT_LANGUAGE,
            "accept-encoding": "identity",
            "cookie": LOGIN_COOKIE,
        }
        _LOGGER.debug("Logging in to OBI (%s)", LOGIN_URL)

        try:
            async with self._session.post(
                LOGIN_URL,
                json={"email": self._email, "password": self._password},
                headers=headers,
                timeout=_REQUEST_TIMEOUT,
            ) as resp:
                if resp.status in (401, 403):
                    await _log_http_error(resp, "OBI login")
                    raise ObiAuthError(
                        f"Login failed with HTTP {resp.status}: invalid credentials"
                    )
                if resp.status >= 400:
                    await _log_http_error(resp, "OBI login")
                    raise ObiConnectionError(
                        f"Login request failed with HTTP {resp.status}"
                    )
                try:
                    data = await resp.json(content_type=None)
                except ValueError as err:
                    text = await _safe_text(resp)
                    _LOGGER.error(
                        "OBI login returned invalid JSON (HTTP %s): %s",
                        resp.status,
                        _truncate(text),
                    )
                    raise ObiConnectionError(
                        "Received invalid response from OBI login"
                    ) from err
        except aiohttp.ClientConnectorDNSError as err:
            _LOGGER.error("DNS resolution failed while logging in to OBI: %s", err)
            raise ObiConnectionError(
                "DNS resolution failed for the OBI login endpoint"
            ) from err
        except aiohttp.ClientSSLError as err:
            _LOGGER.error("SSL/TLS error while logging in to OBI: %s", err)
            raise ObiConnectionError(
                "SSL/TLS error while connecting to the OBI login endpoint"
            ) from err
        except (asyncio.TimeoutError, aiohttp.ServerTimeoutError) as err:
            _LOGGER.error("Timeout while logging in to OBI: %s", err)
            raise ObiConnectionError(
                "Timeout while connecting to the OBI login endpoint"
            ) from err
        except aiohttp.ClientConnectorError as err:
            _LOGGER.error("Could not connect to the OBI login endpoint: %s", err)
            raise ObiConnectionError(
                "Could not connect to the OBI login endpoint"
            ) from err
        except aiohttp.ClientError as err:
            _LOGGER.error("Network error while logging in to OBI: %s", err)
            raise ObiConnectionError("Network error during OBI login") from err

        token = data.get("token") if isinstance(data, dict) else None
        if not token:
            _LOGGER.error("OBI login response did not contain a token")
            raise ObiAuthError("Login response did not contain a token")

        self._token = token
        self._token_obtained_at = datetime.now(timezone.utc)
        _LOGGER.debug("OBI login succeeded")

    def _api_headers(self, accept: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "x-api-key": API_KEY,
            "x-app-type": "b2c",
            "Accept": accept,
            "accept-language": ACCEPT_LANGUAGE,
            "user-agent": USER_AGENT,
        }

    async def _ensure_logged_in(self) -> None:
        if self._token_is_stale():
            await self.async_login()

    async def _authenticated_get(
        self, url: str, *, accept: str, params: dict[str, Any] | None = None
    ) -> Any:
        await self._ensure_logged_in()

        for attempt in range(2):
            headers = self._api_headers(accept)
            try:
                async with self._session.get(
                    url, headers=headers, params=params, timeout=_REQUEST_TIMEOUT
                ) as resp:
                    if resp.status == 401:
                        if attempt == 0:
                            _LOGGER.debug(
                                "OBI API returned 401 for %s, refreshing token and retrying",
                                url,
                            )
                            await self.async_login()
                            continue
                        await _log_http_error(resp, f"OBI request to {url}")
                        raise ObiAuthError("Not authorized after refreshing token")
                    if resp.status == 404:
                        _LOGGER.warning("OBI resource not found (HTTP 404): %s", url)
                        raise ObiNotFoundError(f"Resource not found: {url}")
                    if resp.status >= 400:
                        await _log_http_error(resp, f"OBI request to {url}")
                        raise ObiConnectionError(
                            f"Request to {url} failed with HTTP {resp.status}"
                        )
                    try:
                        return await resp.json(content_type=None)
                    except ValueError as err:
                        text = await _safe_text(resp)
                        _LOGGER.error(
                            "OBI response for %s was not valid JSON (HTTP %s): %s",
                            url,
                            resp.status,
                            _truncate(text),
                        )
                        raise ObiConnectionError(
                            f"Received invalid response from {url}"
                        ) from err
            except aiohttp.ClientConnectorDNSError as err:
                _LOGGER.error("DNS resolution failed requesting %s: %s", url, err)
                raise ObiConnectionError(f"DNS resolution failed for {url}") from err
            except aiohttp.ClientSSLError as err:
                _LOGGER.error("SSL/TLS error requesting %s: %s", url, err)
                raise ObiConnectionError(f"SSL/TLS error requesting {url}") from err
            except (asyncio.TimeoutError, aiohttp.ServerTimeoutError) as err:
                _LOGGER.error("Timeout requesting %s: %s", url, err)
                raise ObiConnectionError(f"Timeout requesting {url}") from err
            except aiohttp.ClientConnectorError as err:
                _LOGGER.error("Could not connect to %s: %s", url, err)
                raise ObiConnectionError(f"Could not connect to {url}") from err
            except aiohttp.ClientError as err:
                _LOGGER.error("Network error requesting %s: %s", url, err)
                raise ObiConnectionError(f"Network error requesting {url}") from err

        raise ObiAuthError("Not authorized after refreshing token")

    async def async_get_bridges(self) -> list[dict[str, Any]]:
        """Return the list of bridges (households) with their sensors."""
        data = await self._authenticated_get(BRIDGES_URL, accept=ACCEPT_BRIDGES)
        if not isinstance(data, list):
            _LOGGER.error(
                "Unexpected response type for /bridges: %s", type(data).__name__
            )
            raise ObiConnectionError("Unexpected response format for /bridges")
        return data

    async def async_get_historical_data(
        self, hh_id: str, mid_id: str, duration: str
    ) -> list[dict[str, Any]]:
        """Return historical measurements for the given bridge/sensor."""
        url = HISTORICAL_DATA_URL_TEMPLATE.format(hh_id=hh_id, mid_id=mid_id)
        end = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        params = {
            "end": end,
            "duration": duration,
            "measures": "energy,negative_energy",
        }
        data = await self._authenticated_get(url, accept=ACCEPT_HISTORICAL, params=params)
        if not isinstance(data, list):
            _LOGGER.error(
                "Unexpected response type for historical data: %s", type(data).__name__
            )
            raise ObiConnectionError("Unexpected response format for historical data")
        return data
