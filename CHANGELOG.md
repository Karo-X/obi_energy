# Changelog

## v0.2.0

Adds optional live tracking (PR #13, contributed by @la-sina), plus a fix for
stale `energy`/`negative_energy` readings that affects everyone.

### Added

- **Live tracking** (disabled by default, enable via the integration's
  **Configure** options): opens a WebSocket connection to OBI's live-mode
  endpoint and requests a fast (2-second) sensor upload interval, exposing
  four new diagnostic entities — `sensor.obi_live_power`,
  `sensor.obi_live_rssi`, `sensor.obi_live_battery`, and
  `sensor.obi_live_last_message`. `sensor.obi_live_power` reports raw watts as
  sent by OBI; the sign convention for consumption vs. feed-in is not yet
  confirmed. Turning live tracking off (or unloading/reloading the
  integration) restores the sensor's normal 300-second upload interval so the
  physical device doesn't stay in fast-report mode.

### Fixed

- Historical polling for `energy`/`negative_energy` no longer stalls while
  live tracking is active — the live-data listener previously nudged the
  coordinator's regular refresh timer on every live message, which could
  starve the normal historical-data poll when live updates arrived every
  couple of seconds.
- `_latest_measurement` now also recognizes a `time` field (in addition to
  `timestamp`) on historical records, matching a response variant observed
  from OBI's API.

## v0.1.2

Reduces the default `historical_duration` from `PT6H` to `PT15M`.

Community testing (see the OBI Energy Tracker thread on photovoltaikforum.de)
found that a large historical-data window like `PT6H` can make OBI's API
return older data instead of the latest reading, even with the v0.1.1 fix
applied — the symptom looks identical to issue #10 but is caused by the
window size itself, not the request format. Users who already changed
`historical_duration` in the options manually are unaffected; this only
changes the out-of-the-box default for new setups. The options description
now also documents this tradeoff directly in the UI.

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
