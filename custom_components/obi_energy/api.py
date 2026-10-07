"""API client for the OBI / heyOBI Energy Tracking backend.

The JWT obtained on login is only ever kept in memory on this client. It is
never logged, never persisted, and never exposed to entities or attributes.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

from .const import (
    ACCEPT_BRIDGES,
    ACCEPT_HISTORICAL,
    ACCEPT_LANGUAGE,
    ACCEPT_SENSOR,
    API_KEY,
    BRIDGES_URL,
    HISTORICAL_DATA_URL_TEMPLATE,
    LOGIN_COOKIE,
    LOGIN_COUNTRY,
    LOGIN_HOST,
    LOGIN_ORIGIN,
    LOGIN_REFERER,
    LOGIN_URL,
    LIVE_DATA_URL,
    LIVE_USER_AGENT,
    SENSOR_URL_TEMPLATE,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 30
_MAX_LOG_BODY_CHARS = 300

# Safety margin subtracted from the JWT's own `exp` claim before the token is
# considered stale. Measured against the live API on 2026-09-18, OBI issues
# tokens with a 180-day lifetime (iat 2026-09-18 -> exp 2027-03-17), so
# honoring `exp` instead of re-logging in on a fixed 55-minute timer removes
# essentially all password logins.
_TOKEN_EXPIRY_MARGIN = timedelta(minutes=5)
# ...but don't blindly ride a single token for half a year: cap its age so a
# server-side session invalidation is recovered from proactively instead of
# only via a 401. One login per week is still ~180x fewer than today.
_MAX_TOKEN_AGE = timedelta(days=7)
# Never send two password logins closer together than this, no matter how many
# callers ask for one (historical poll, live WebSocket, live-mode PATCH, ...).
_MIN_LOGIN_INTERVAL = timedelta(seconds=60)
# After the server rejects the password, stop trying for a while and grow the
# pause on every further rejection. Repeatedly replaying a password that the
# backend just refused is what turns a single 401 into a locked account.
_AUTH_BACKOFF_INITIAL = timedelta(minutes=5)
_AUTH_BACKOFF_MAX = timedelta(hours=6)
# A 401 on an API call is only treated as "token expired" if the token is
# actually old enough for that to be plausible.
_MIN_TOKEN_AGE_FOR_REFRESH = timedelta(seconds=30)
# OBI has been seen answering "Invalid token." for a token it had issued only
# moments before. That is not a credentials problem, so instead of another
# login the request is retried once with the same token after a short pause.
_FRESH_TOKEN_RETRY_DELAY = 5
# If the token is still rejected after that, 401-triggered re-logins are
# paused with a growing backoff, so a misbehaving backend can never drive a
# stream of password logins. Any accepted request resets it.
_TOKEN_REJECT_BACKOFF_INITIAL = timedelta(minutes=5)
_TOKEN_REJECT_BACKOFF_MAX = timedelta(hours=6)
# Per request: the original attempt, one retry after a re-login, and one
# delayed retry with a freshly issued token.
_MAX_REQUEST_ATTEMPTS = 3


class ObiApiError(Exception):
    """Base exception for OBI API errors."""


class ObiAuthError(ObiApiError):
    """Raised when authentication fails (bad credentials or expired session)."""


class ObiConnectionError(ObiApiError):
    """Raised on network or unexpected HTTP errors."""


class ObiTokenRejectedError(ObiConnectionError):
    """Raised when OBI rejects a token even though the login succeeded.

    The password was accepted, so asking the user to re-authenticate would not
    help; callers treat this like any other transient error and retry later.
    """


class ObiNotFoundError(ObiApiError):
    """Raised when a resource (e.g. /bridges) returns 404."""


class _UnauthorizedRetry:
    """Recovery steps already used by a single request after a 401."""

    def __init__(self) -> None:
        self.logged_in = False
        self.waited = False


_ISO8601_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)


def _parse_iso8601_duration(duration: str) -> timedelta:
    """Parse a simple ISO 8601 duration (e.g. PT6H, P1D) into a timedelta."""
    match = _ISO8601_DURATION_RE.match(duration.strip())
    if not match or not any(match.groups()):
        raise ValueError(f"Unsupported ISO 8601 duration: {duration!r}")
    parts = {key: int(value) for key, value in match.groupdict(default="0").items()}
    return timedelta(
        days=parts["days"],
        hours=parts["hours"],
        minutes=parts["minutes"],
        seconds=parts["seconds"],
    )


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


def _jwt_expiry(token: str) -> datetime | None:
    """Return the `exp` claim of a JWT, or None if it can't be read.

    The signature is intentionally *not* verified - we only need the expiry
    the issuer itself put into the token, and the token is never trusted for
    anything but deciding when to log in again.
    """
    try:
        payload_segment = token.split(".")[1]
    except (AttributeError, IndexError):
        return None

    padding = "=" * (-len(payload_segment) % 4)
    try:
        payload = json.loads(
            base64.urlsafe_b64decode(payload_segment + padding).decode("utf-8")
        )
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None

    exp = payload.get("exp") if isinstance(payload, dict) else None
    if not isinstance(exp, (int, float)) or isinstance(exp, bool):
        return None
    try:
        return datetime.fromtimestamp(exp, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None


async def _log_http_error(resp: aiohttp.ClientResponse, context: str) -> None:
    """Log HTTP status, response headers and a truncated body.

    Only the server's *response* headers are logged (never the request
    headers we sent), so no cookie, token or password ever ends up here.
    """
    body = await _safe_text(resp)
    _LOGGER.error(
        "%s failed with HTTP %s. Response headers: %s. Response body: %s",
        context,
        resp.status,
        dict(resp.headers),
        _truncate(body),
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
        self._token_expires_at: datetime | None = None
        self._login_lock = asyncio.Lock()
        self._last_login_attempt_at: datetime | None = None
        self._auth_failures = 0
        self._auth_blocked_until: datetime | None = None
        self._token_rejections = 0
        self._relogin_blocked_until: datetime | None = None
        self._login_returned_same_token = False

    def update_credentials(self, email: str, password: str) -> None:
        """Update the credentials used for future logins."""
        self._email = email
        self._password = password
        self._token = None
        self._token_obtained_at = None
        self._token_expires_at = None
        # Fresh credentials: allow an immediate attempt again.
        self._auth_failures = 0
        self._auth_blocked_until = None
        self._last_login_attempt_at = None
        self._token_rejections = 0
        self._relogin_blocked_until = None

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
        now = datetime.now(timezone.utc)
        if self._token_expires_at is not None:
            # Trust the token's own lifetime (bounded by _MAX_TOKEN_AGE);
            # only log in again shortly before it actually expires.
            deadline = min(
                self._token_expires_at - _TOKEN_EXPIRY_MARGIN,
                self._token_obtained_at + _MAX_TOKEN_AGE,
            )
            return now >= deadline
        return now - self._token_obtained_at >= self._login_refresh_interval

    async def async_login(self) -> None:
        """Log in to OBI, serialized against any concurrent login attempt."""
        async with self._login_lock:
            await self._async_login_locked()

    async def _async_handle_unauthorized(
        self, rejected_token: str | None, retry: _UnauthorizedRetry
    ) -> bool:
        """React to a 401 for `rejected_token`; return whether to retry.

        The decision is made about the token that was actually rejected, not
        whatever token is current by the time the 401 arrives. When the
        backend invalidates a token, concurrent requests (historical poll,
        live-mode PATCH, WebSocket) all get a 401; the first one logs in
        again, and the others must simply retry with that new token rather
        than mistake it for "a fresh token was rejected" and give up.

        A request logs in again at most once, and if a freshly issued token
        is rejected it is retried once more after a short pause, without
        another login.
        """
        async with self._login_lock:
            if self._token is not None and self._token != rejected_token:
                _LOGGER.debug(
                    "Token was already refreshed by another task; retrying with it"
                )
                return True
            token_is_fresh = retry.logged_in or not self._token_age_allows_refresh()
            if not token_is_fresh:
                if self._relogin_is_blocked():
                    return False
                retry.logged_in = True
                await self._async_login_locked()
                return True

        if retry.waited:
            return False
        retry.waited = True
        _LOGGER.debug(
            "OBI rejected a token issued %ss ago; retrying once in %ss without "
            "logging in again",
            self._token_age_seconds(),
            _FRESH_TOKEN_RETRY_DELAY,
        )
        await asyncio.sleep(_FRESH_TOKEN_RETRY_DELAY)
        return True

    def _relogin_is_blocked(self) -> bool:
        return (
            self._relogin_blocked_until is not None
            and datetime.now(timezone.utc) < self._relogin_blocked_until
        )

    def _token_age_seconds(self) -> int | None:
        if self._token_obtained_at is None:
            return None
        return int((datetime.now(timezone.utc) - self._token_obtained_at).total_seconds())

    def _note_token_accepted(self) -> None:
        """Reset the token-rejection backoff after a successful request."""
        self._token_rejections = 0
        self._relogin_blocked_until = None

    def _token_rejected(
        self, context: str, retry: _UnauthorizedRetry
    ) -> ObiTokenRejectedError:
        """Log why a 401 could not be recovered from and pause re-logins.

        Never logs the token itself, only facts about it.
        """
        error = ObiTokenRejectedError(f"{context} was rejected with HTTP 401")
        if not (retry.logged_in or retry.waited):
            # Re-logins are already paused; nothing new was tried, so don't
            # grow the backoff on every poll that runs into it.
            _LOGGER.debug(
                "%s: OBI rejected the token (HTTP 401); 401-triggered logins are "
                "paused until %s",
                context,
                self._relogin_blocked_until,
            )
            return error
        self._token_rejections += 1
        backoff = min(
            _TOKEN_REJECT_BACKOFF_INITIAL * (2 ** (self._token_rejections - 1)),
            _TOKEN_REJECT_BACKOFF_MAX,
        )
        self._relogin_blocked_until = datetime.now(timezone.utc) + backoff
        _LOGGER.warning(
            "%s: OBI rejected the token (HTTP 401) although it was issued %ss ago "
            "(logged in again during this request: %s, retried after a pause: %s, "
            "last login returned the previous token again: %s, token expires: %s). "
            "The password was accepted, so this is not a credentials problem; "
            "pausing 401-triggered logins for %s (rejection #%s).",
            context,
            self._token_age_seconds(),
            retry.logged_in,
            retry.waited,
            self._login_returned_same_token,
            self._token_expires_at.isoformat() if self._token_expires_at else "unknown",
            backoff,
            self._token_rejections,
        )
        return error

    def _guard_login_rate(self) -> None:
        """Refuse to send a password login that would be abusive.

        OBI's backend appears to react badly to accounts that authenticate
        very often or replay a rejected password, so both cases are stopped
        here, client-side, before a request is sent.
        """
        now = datetime.now(timezone.utc)

        if self._auth_blocked_until is not None and now < self._auth_blocked_until:
            wait = (self._auth_blocked_until - now).total_seconds()
            raise ObiAuthError(
                "OBI rejected the stored password earlier; not retrying for another "
                f"{int(wait)}s to avoid locking the account. "
                "Re-authenticate with a working password to retry immediately."
            )

        if (
            self._last_login_attempt_at is not None
            and now - self._last_login_attempt_at < _MIN_LOGIN_INTERVAL
        ):
            wait = (
                _MIN_LOGIN_INTERVAL - (now - self._last_login_attempt_at)
            ).total_seconds()
            raise ObiConnectionError(
                f"Skipping OBI login: another login was sent {int(_MIN_LOGIN_INTERVAL.total_seconds() - wait)}s ago"
            )

    def _note_login_rejected(self) -> None:
        """Grow the local backoff after the backend rejected the password."""
        self._auth_failures += 1
        backoff = min(
            _AUTH_BACKOFF_INITIAL * (2 ** (self._auth_failures - 1)),
            _AUTH_BACKOFF_MAX,
        )
        self._auth_blocked_until = datetime.now(timezone.utc) + backoff
        _LOGGER.warning(
            "OBI rejected the login (failure #%s). Pausing login attempts for %s "
            "to avoid triggering an account lockout.",
            self._auth_failures,
            backoff,
        )

    async def _async_login_locked(self) -> None:
        """Log in to OBI and store the resulting JWT in memory only."""
        self._guard_login_rate()
        self._last_login_attempt_at = datetime.now(timezone.utc)
        # Serialize the body ourselves - compact, no whitespace - and send it
        # via `data=` (like the previously working YAML REST sensor did),
        # instead of aiohttp's `json=` shortcut, which re-derives its own
        # content-type/content-length handling and can conflict with the
        # exact headers OBI (and the CloudFront in front of it) expect.
        payload = json.dumps(
            {
                "password": self._password,
                "country": LOGIN_COUNTRY,
                "email": self._email,
            },
            separators=(",", ":"),
        )
        payload_bytes = payload.encode("utf-8")

        headers = {
            "content-type": "application/json",
            "accept": "*/*",
            "user-agent": USER_AGENT,
            "accept-language": ACCEPT_LANGUAGE,
            "accept-encoding": "identity",
            "cookie": LOGIN_COOKIE,
            "content-length": str(len(payload_bytes)),
            "host": LOGIN_HOST,
            "origin": LOGIN_ORIGIN,
            "referer": LOGIN_REFERER,
        }
        _LOGGER.debug("Logging in to OBI (%s)", LOGIN_URL)

        try:
            async with self._session.post(
                LOGIN_URL,
                data=payload_bytes,
                headers=headers,
                timeout=_REQUEST_TIMEOUT,
            ) as resp:
                if resp.status in (401, 403):
                    await _log_http_error(resp, "OBI login")
                    self._note_login_rejected()
                    raise ObiAuthError(
                        f"Login failed with HTTP {resp.status}: invalid credentials"
                    )
                if resp.status == 429:
                    await _log_http_error(resp, "OBI login")
                    retry_after = resp.headers.get("Retry-After")
                    delay = _AUTH_BACKOFF_INITIAL
                    if retry_after and retry_after.isdigit():
                        delay = max(delay, timedelta(seconds=int(retry_after)))
                    self._auth_blocked_until = datetime.now(timezone.utc) + delay
                    raise ObiConnectionError(
                        f"OBI login was rate limited (HTTP 429); pausing for {delay}"
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

        self._login_returned_same_token = token == self._token
        if self._login_returned_same_token:
            _LOGGER.warning(
                "OBI login returned the same token that was already in use"
            )
        self._token = token
        self._token_obtained_at = datetime.now(timezone.utc)
        self._token_expires_at = _jwt_expiry(token)
        self._auth_failures = 0
        self._auth_blocked_until = None
        if self._token_expires_at is not None:
            _LOGGER.debug(
                "OBI login succeeded; token valid until %s (next login shortly before that)",
                self._token_expires_at.isoformat(),
            )
        else:
            _LOGGER.debug(
                "OBI login succeeded; token has no readable expiry, falling back to the "
                "configured login refresh interval (%s)",
                self._login_refresh_interval,
            )

    def _api_headers(self, accept: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "x-api-key": API_KEY,
            "x-app-type": "b2c",
            "Accept": accept,
            "accept-language": ACCEPT_LANGUAGE,
            "user-agent": USER_AGENT,
            # OBI's API is fronted by CloudFront. Ask it (and any
            # intermediate cache) to not serve a stale cached response for
            # historical-data polls, which otherwise can appear to "stop
            # updating" even though fresh readings exist upstream.
            "cache-control": "no-cache",
            "pragma": "no-cache",
        }

    async def _ensure_logged_in(self) -> None:
        if not self._token_is_stale():
            return
        async with self._login_lock:
            # Another task may have refreshed the token while we waited.
            if not self._token_is_stale():
                return
            await self._async_login_locked()

    async def _authenticated_get(
        self, url: str, *, accept: str, params: dict[str, Any] | None = None
    ) -> Any:
        await self._ensure_logged_in()

        retry = _UnauthorizedRetry()
        for attempt in range(_MAX_REQUEST_ATTEMPTS):
            headers = self._api_headers(accept)
            stale_token = self._token
            try:
                async with self._session.get(
                    url, headers=headers, params=params, timeout=_REQUEST_TIMEOUT
                ) as resp:
                    if resp.status == 401:
                        if (
                            attempt < _MAX_REQUEST_ATTEMPTS - 1
                            and await self._async_handle_unauthorized(stale_token, retry)
                        ):
                            _LOGGER.debug(
                                "OBI API returned 401 for %s, retrying", url
                            )
                            continue
                        await _log_http_error(resp, f"OBI request to {url}")
                        raise self._token_rejected(f"OBI request to {url}", retry)
                    if resp.status == 404:
                        _LOGGER.warning("OBI resource not found (HTTP 404): %s", url)
                        raise ObiNotFoundError(f"Resource not found: {url}")
                    if resp.status >= 400:
                        await _log_http_error(resp, f"OBI request to {url}")
                        raise ObiConnectionError(
                            f"Request to {url} failed with HTTP {resp.status}"
                        )
                    self._note_token_accepted()
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

        raise ObiTokenRejectedError(f"OBI request to {url} was rejected with HTTP 401")

    def _token_age_allows_refresh(self) -> bool:
        """Return whether a 401 can plausibly mean "token expired".

        A 401 received seconds after a successful login is *not* an expired
        token - logging in again would only add another password attempt on
        an account the backend is already unhappy about.
        """
        if self._token_obtained_at is None:
            return True
        return (
            datetime.now(timezone.utc) - self._token_obtained_at
            >= _MIN_TOKEN_AGE_FOR_REFRESH
        )

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

        try:
            delta = _parse_iso8601_duration(duration)
        except ValueError as err:
            _LOGGER.error("Invalid historical duration %r: %s", duration, err)
            raise ObiConnectionError(f"Invalid historical duration: {duration}") from err

        # OBI's API expects a single ISO 8601 time interval
        # (<start>/<duration>), not separate end/duration parameters.
        start = datetime.now(timezone.utc) - delta
        start_str = start.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        params = {
            "duration": f"{start_str}/{duration}",
            "measures": "energy,negative_energy",
        }
        data = await self._authenticated_get(url, accept=ACCEPT_HISTORICAL, params=params)
        if not isinstance(data, list):
            _LOGGER.error(
                "Unexpected response type for historical data: %s", type(data).__name__
            )
            raise ObiConnectionError("Unexpected response format for historical data")
        return data

    async def async_set_sensor_upload_interval(
        self, mid_id: str, upload_interval: int
    ) -> dict[str, Any]:
        """Set the upload interval for a sensor and return the updated sensor."""
        await self._ensure_logged_in()

        url = SENSOR_URL_TEMPLATE.format(mid_id=mid_id)
        payload = json.dumps(
            {"id": mid_id, "uploadInterval": upload_interval},
            separators=(",", ":"),
        )
        payload_bytes = payload.encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": ACCEPT_SENSOR,
            "Accept-Language": ACCEPT_LANGUAGE,
            "Content-Type": ACCEPT_SENSOR,
            "Content-Length": str(len(payload_bytes)),
            "User-Agent": LIVE_USER_AGENT,
            "X-Platform": "iOS",
            "X-Lib-Version": "26.6.9",
        }

        retry = _UnauthorizedRetry()
        for attempt in range(_MAX_REQUEST_ATTEMPTS):
            try:
                async with self._session.patch(
                    url,
                    data=payload_bytes,
                    headers=headers,
                    timeout=_REQUEST_TIMEOUT,
                ) as resp:
                    if resp.status == 401:
                        if (
                            attempt < _MAX_REQUEST_ATTEMPTS - 1
                            and await self._async_handle_unauthorized(
                                headers["Authorization"][7:], retry
                            )
                        ):
                            _LOGGER.debug("OBI sensor update returned 401, retrying")
                            headers["Authorization"] = f"Bearer {self._token}"
                            continue
                        await _log_http_error(resp, f"OBI sensor update to {url}")
                        raise self._token_rejected(f"OBI sensor update to {url}", retry)
                    if resp.status == 403:
                        await _log_http_error(resp, f"OBI sensor update to {url}")
                        raise ObiAuthError(
                            f"Sensor update failed with HTTP {resp.status}"
                        )
                    if resp.status == 404:
                        _LOGGER.warning("OBI sensor not found (HTTP 404): %s", url)
                        raise ObiNotFoundError(f"Sensor not found: {url}")
                    if resp.status >= 400:
                        await _log_http_error(resp, f"OBI sensor update to {url}")
                        raise ObiConnectionError(
                            f"Sensor update to {url} failed with HTTP {resp.status}"
                        )
                    try:
                        data = await resp.json(content_type=None)
                    except ValueError as err:
                        text = await _safe_text(resp)
                        _LOGGER.error(
                            "OBI sensor update response was not valid JSON (HTTP %s): %s",
                            resp.status,
                            _truncate(text),
                        )
                        raise ObiConnectionError(
                            "Received invalid response from OBI sensor update"
                        ) from err
                    if not isinstance(data, dict):
                        _LOGGER.error(
                            "Unexpected response type for sensor update: %s",
                            type(data).__name__,
                        )
                        raise ObiConnectionError(
                            "Unexpected response format for sensor update"
                        )
                    self._note_token_accepted()
                    return data
            except aiohttp.ClientConnectorDNSError as err:
                _LOGGER.error("DNS resolution failed updating %s: %s", url, err)
                raise ObiConnectionError(f"DNS resolution failed for {url}") from err
            except aiohttp.ClientSSLError as err:
                _LOGGER.error("SSL/TLS error updating %s: %s", url, err)
                raise ObiConnectionError(f"SSL/TLS error updating {url}") from err
            except (asyncio.TimeoutError, aiohttp.ServerTimeoutError) as err:
                _LOGGER.error("Timeout updating %s: %s", url, err)
                raise ObiConnectionError(f"Timeout updating {url}") from err
            except aiohttp.ClientConnectorError as err:
                _LOGGER.error("Could not connect to %s: %s", url, err)
                raise ObiConnectionError(f"Could not connect to {url}") from err
            except aiohttp.ClientError as err:
                _LOGGER.error("Network error updating %s: %s", url, err)
                raise ObiConnectionError(f"Network error updating {url}") from err

        raise ObiTokenRejectedError(f"OBI sensor update to {url} was rejected with HTTP 401")

    async def async_connect_live_data(
        self, hh_id: str, mid_id: str
    ) -> aiohttp.ClientWebSocketResponse:
        """Open the live-data WebSocket for the given bridge/sensor."""
        await self._ensure_logged_in()

        params = {
            "bridgeId": hh_id,
            "sensorId": mid_id,
        }
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "*/*",
            "Accept-Language": ACCEPT_LANGUAGE,
            "User-Agent": LIVE_USER_AGENT,
            "X-Platform": "iOS",
            "X-Lib-Version": "26.6.9",
        }

        retry = _UnauthorizedRetry()
        for attempt in range(_MAX_REQUEST_ATTEMPTS):
            try:
                websocket = await self._session.ws_connect(
                    LIVE_DATA_URL,
                    params=params,
                    headers=headers,
                    timeout=_REQUEST_TIMEOUT,
                    heartbeat=30,
                    compress=15,
                )
                self._note_token_accepted()
                return websocket
            except aiohttp.WSServerHandshakeError as err:
                if err.status == 401:
                    if (
                        attempt < _MAX_REQUEST_ATTEMPTS - 1
                        and await self._async_handle_unauthorized(
                            headers["Authorization"][7:], retry
                        )
                    ):
                        _LOGGER.debug("OBI live WebSocket returned 401, retrying")
                        headers["Authorization"] = f"Bearer {self._token}"
                        continue
                    raise self._token_rejected("OBI live WebSocket", retry) from err
                if err.status == 403:
                    _LOGGER.error(
                        "OBI live WebSocket authorization failed with HTTP %s",
                        err.status,
                    )
                    raise ObiAuthError(
                        f"Live WebSocket authorization failed with HTTP {err.status}"
                    ) from err
                _LOGGER.error(
                    "OBI live WebSocket handshake failed with HTTP %s",
                    err.status,
                )
                raise ObiConnectionError(
                    f"Live WebSocket handshake failed with HTTP {err.status}"
                ) from err
            except aiohttp.ClientConnectorDNSError as err:
                _LOGGER.error("DNS resolution failed for OBI live WebSocket: %s", err)
                raise ObiConnectionError(
                    "DNS resolution failed for the OBI live WebSocket endpoint"
                ) from err
            except aiohttp.ClientSSLError as err:
                _LOGGER.error("SSL/TLS error on OBI live WebSocket: %s", err)
                raise ObiConnectionError(
                    "SSL/TLS error while connecting to the OBI live WebSocket endpoint"
                ) from err
            except (asyncio.TimeoutError, aiohttp.ServerTimeoutError) as err:
                _LOGGER.error("Timeout connecting to OBI live WebSocket: %s", err)
                raise ObiConnectionError(
                    "Timeout while connecting to the OBI live WebSocket endpoint"
                ) from err
            except aiohttp.ClientConnectorError as err:
                _LOGGER.error("Could not connect to OBI live WebSocket: %s", err)
                raise ObiConnectionError(
                    "Could not connect to the OBI live WebSocket endpoint"
                ) from err
            except aiohttp.ClientError as err:
                _LOGGER.error("Network error on OBI live WebSocket: %s", err)
                raise ObiConnectionError("Network error during OBI live WebSocket") from err

        raise ObiTokenRejectedError("OBI live WebSocket was rejected with HTTP 401")
