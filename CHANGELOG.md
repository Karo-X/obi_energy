# Changelog

## v0.1.1

Fixes #10 (energy/negative_energy measurements stop updating even though
the OBI app shows fresh readings):

- `/historical-data` now sends a single ISO 8601 `<start>/<duration>`
  interval as one `duration` parameter, instead of separate `end=`/
  `duration=` query parameters - matching the request shape confirmed to
  work in another OBI HACS integration. The previous two-parameter form
  may not have been parsed correctly by OBI's backend.
- Added `Cache-Control: no-cache` / `Pragma: no-cache` headers on every
  authenticated request, in case CloudFront (which fronts OBI's API) was
  serving a stale cached response.
- Added debug-level logging of each historical-data poll (record count,
  latest energy/negative_energy timestamp and value) to help diagnose any
  remaining staleness directly from the Home Assistant log.

## v0.1.0

Initial working release:
- UI config flow
- OBI login with country=de
- JWT kept only in memory
- bridge discovery
- energy and feed-in sensors
- kWh sensors compatible with HA Energy Dashboard
- diagnostics sensors
- automatic token refresh / 401 retry
- debug logging without token/password leakage

### Details

First tagged release. The integration is fully config-flow based (no YAML),
logs into the OBI/heyOBI Energy Tracking API, discovers the bridge/sensor,
and exposes native Home Assistant entities for consumption, feed-in, battery,
connectivity and diagnostics.

#### Added

- Config flow: email/password entry, automatic bridge/sensor discovery with
  a picker for multiple bridges, and a manual `HH_ID`/`MID_ID` fallback when
  `/bridges` is unavailable.
- Reauth flow (triggered automatically on authentication failure) and a
  reconfigure flow to update credentials later.
- Options flow: measurement scan interval, login refresh interval,
  historical data duration, debug logging toggle, and manual `HH_ID`/`MID_ID`
  overrides.
- `DataUpdateCoordinator`-based polling with sensors for:
  `sensor.obi_energy`, `sensor.obi_energy_kwh`, `sensor.obi_negative_energy`,
  `sensor.obi_einspeisung_kwh`, `sensor.obi_netto_energy_kwh`,
  `sensor.obi_bridge_battery`, `sensor.obi_bridge_connection_strength`,
  `sensor.obi_last_record_received`, and `binary_sensor.obi_bridge_online`.
- Diagnostics support (redacts email/password; the session token is never
  persisted, logged, or exposed anywhere).
- German and English translations for the config flow, options flow, and
  entity names.
- `hacs.json` for HACS custom-repository installation.

#### Fixed

- Login now sends the exact request shape confirmed via a mitmproxy capture
  of the real heyOBI app: a compact JSON body (`{"password", "country":
  "de", "email"}`, no whitespace) sent as raw bytes via `data=` with an
  explicit `Content-Length`, plus the `Host`/`Origin`/`Referer`/`Cookie`
  headers the app sends. Earlier attempts using aiohttp's `json=` shortcut
  were rejected by CloudFront in front of OBI's login endpoint.
- Entities become `unavailable` (instead of reporting `0`) when login fails,
  `/bridges` can't be retrieved, or historical data is empty/invalid, so
  Home Assistant's Energy Dashboard statistics never see a false reading.
- Config flow and API client now log the real failure reason (DNS, SSL,
  timeout, HTTP status with response headers/truncated body, JSON decode
  errors) instead of a generic "cannot connect", without ever logging
  tokens, passwords, or full request bodies.
- Device info is consistent across all entities (`manufacturer: "OBI"`,
  `model: "heyOBI Energy Tracking"`, device name `"OBI Energy Bridge"`), and
  entity names use `translation_key` so they render correctly per language.
  Each entity's `entity_id` is pinned via `suggested_object_id` (e.g.
  `sensor.obi_energy`) so it stays short and stable regardless of the
  translated display name.
