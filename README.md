# OBI Energy for Home Assistant

A custom Home Assistant integration for the OBI / heyOBI Energy Tracking
system. It logs into the OBI backend, discovers your energy-tracking
bridge/sensor, and exposes native Home Assistant entities — no YAML REST
sensors required.

> **Not an official OBI product.** This integration is community-built and
> is not affiliated with, endorsed by, or supported by OBI or heyOBI. Use at
> your own risk; the upstream API is undocumented and may change at any
> time.

## What is read out?

Every scan interval, the integration fetches:

- Bridge/sensor status via `GET /bridges` (online state, battery level,
  connection strength, last record timestamp, upload interval, firmware and
  hardware version).
- Historical meter measurements via `GET /historical-data/{hh_id}/{mid_id}/meter`
  for the `energy` and `negative_energy` measures.

### `energy` vs. `negative_energy`

- **`energy`** is the cumulative energy **consumed/drawn** from the grid
  ("Strombezug"), in Wh.
- **`negative_energy`** is the cumulative energy **fed back into the grid**
  ("Einspeisung"), e.g. from solar production, in Wh.

Both values are cumulative counters, similar to a physical meter — they only
ever increase (until a meter reset). That's why the corresponding sensors
use `state_class: total_increasing`.

### Wh vs. kWh

The OBI API reports values in **Wh**. This integration exposes both the raw
Wh sensors and derived **kWh** sensors (value ÷ 1000) since most Home
Assistant energy tooling — and the Energy Dashboard — expects kWh.

## Created entities

| Entity | Unit | Device class | State class |
|---|---|---|---|
| `sensor.obi_energy` | Wh | energy | total_increasing |
| `sensor.obi_energy_kwh` | kWh | energy | total_increasing |
| `sensor.obi_negative_energy` | Wh | energy | total_increasing |
| `sensor.obi_einspeisung_kwh` | kWh | energy | total_increasing |
| `sensor.obi_netto_energy_kwh` | kWh | energy | total (can be negative) |
| `sensor.obi_bridge_battery` | % | battery | – |
| `binary_sensor.obi_bridge_online` | – | connectivity | – |
| `sensor.obi_bridge_connection_strength` | – | – | – (text, e.g. `GOOD_CONNECTION`) |
| `sensor.obi_last_record_received` | – | timestamp | – |

The connection-strength sensor also carries diagnostic attributes: `hh_id`,
`mid_id`, `upload_interval`, `firmware_version`, `hardware_version`. A full
diagnostics dump is also available via **Settings → Devices & Services →
OBI Energy → Download diagnostics**.

If the API returns no data for a measurement (e.g. during a temporary
outage), the corresponding entity becomes **unavailable** rather than
reporting `0`, so your Energy Dashboard statistics stay accurate.

## Installation

### HACS (custom repository)

This integration is not (yet) in the default HACS store, so it needs to be
added as a **custom repository**:

**HACS → Custom repositories → URL `https://github.com/Karo-X/obi_energy` →
Category `Integration` → Install → Restart Home Assistant → Settings →
Devices & Services → Add Integration → OBI Energy.**

Spelled out:

1. Open **HACS → Integrations** in Home Assistant.
2. Click the **⋮** (three-dot) menu in the top right corner and choose
   **Custom repositories**.
3. Add this repository's URL (`https://github.com/Karo-X/obi_energy`) and
   select category **Integration**, then **Add**.
4. Find **OBI Energy** in HACS and click **Install**.
5. Restart Home Assistant.
6. Go to **Settings → Devices & Services → Add Integration** and search for
   **OBI Energy**.

### Manual

1. Copy `custom_components/obi_energy` into your Home Assistant
   `config/custom_components/` directory.
2. Restart Home Assistant.

## Setup (via the UI)

No YAML configuration is needed or supported.

1. Go to **Settings → Devices & Services → Add Integration** and search for
   **OBI Energy**.
2. Enter your OBI/heyOBI **email** and **password**. These are stored in
   Home Assistant's encrypted config entry storage (not in
   `secrets.yaml`, not in YAML at all) and are only used to obtain a
   short-lived session token.
3. The integration logs in and fetches your bridges:
   - If exactly one bridge/sensor is found, it's used automatically.
   - If multiple are found, you'll be asked to pick one.
   - If the bridge list can't be retrieved, you can enter the household ID
     (`HH_ID`) and sensor ID (`MID_ID`) manually.
4. Entities appear automatically — no YAML required.

### Options

After setup, click **Configure** on the integration to adjust:

- **Measurement scan interval** (default: 60 seconds)
- **Login refresh interval** (default: 55 minutes) — how often the session
  token is proactively renewed, independent of the 401-triggered refresh
- **Historical data duration** (default: `PT6H`, ISO 8601 duration)
- **Debug logging**
- **Manual `HH_ID` / `MID_ID` overrides** (useful if `/bridges` starts
  failing after setup)

### Changing your password

Use **Reconfigure** on the integration tile to update your OBI email or
password. If OBI invalidates your session (e.g. after a password change),
Home Assistant will automatically prompt a **Reauthentication** flow.

## Energy Dashboard

To use OBI Energy in the Home Assistant Energy Dashboard:

1. Go to **Settings → Dashboards → Energy**.
2. Under **Electricity grid → Add Consumption**, select
   `sensor.obi_energy_kwh`.
3. If you feed energy back into the grid (solar, etc.), under
   **Return to grid**, select `sensor.obi_einspeisung_kwh`.

Only the kWh, `total_increasing` sensors should be used in the Energy
Dashboard — not the Wh sensors or the net sensor.

## Token & credential handling

- The JWT obtained at login is kept **only in memory** inside the
  integration's API client. It is never stored on disk, never logged, and
  never exposed as an entity, attribute, or diagnostic.
- Your OBI password is never logged.
- On a `401 Unauthorized` response, the integration automatically logs in
  again and retries the request once.
- The token is also proactively renewed before the configured login-refresh
  interval elapses.

## Troubleshooting

### I get repeated login/auth failures (401)

- Double-check your OBI email/password via **Reconfigure**.
- If your OBI account password changed, Home Assistant should prompt a
  **Reauthenticate** notification — follow it to enter the new password.
- Persistent 401s after re-entering correct credentials usually mean OBI
  has changed or rate-limited their login endpoint.

### `/bridges` returns 404 or an empty list

- This can happen if your account has no visible bridges yet, or the
  endpoint is temporarily unavailable.
- Use the **manual `HH_ID` / `MID_ID` override** in the integration options
  to keep the integration running with known IDs.

### "Verbindung zu den OBI-Servern konnte nicht hergestellt werden" / `cannot_connect`

This generic message is shown in the UI for any network-level failure. The
Home Assistant log always has the real cause at `ERROR` level, logged from
`custom_components.obi_energy.api` and `custom_components.obi_energy.config_flow`
— check **Settings → System → Logs** (or `home-assistant.log`) right after
the failed attempt. It will tell you whether the request failed due to DNS
resolution, an SSL/TLS error, a timeout, or a specific HTTP status code
(401/403/404/500/...), plus a truncated (max 300 characters) response body
for HTTP errors — enough to diagnose the problem without exposing your
token or password.

### Entities show "unavailable"

This is expected when the API returns no data for that measurement (rather
than showing a misleading `0`, which would corrupt Energy Dashboard
statistics). Check Home Assistant logs (enable debug logging in the
integration options) for the underlying cause once it recovers.

## Icon & branding

This integration does **not** bundle an OBI/heyOBI logo — trademark and
usage rights for OBI's branding are unclear for a community project, so no
`icon.png`/`logo.png` is included. Entities instead use Home Assistant's
built-in Material Design Icons (e.g. `mdi:transmission-tower` for the bridge
connection-strength sensor); most other entities get a sensible default icon
from their `device_class` (energy, battery, connectivity, timestamp). In the
integrations list, Home Assistant/HACS will show a generic placeholder icon
instead of a brand logo — this is expected and intentional.

## Release notes

See [CHANGELOG.md](CHANGELOG.md) for the version history.

## License

[MIT](LICENSE)

## Security note

Never post your JWT, email, or password in GitHub issues, logs, or
screenshots when reporting problems. Credentials and tokens are deliberately
excluded from all log output. On HTTP errors, the integration does log the
HTTP status code and up to 300 characters of the response body to help with
debugging — review logs before sharing them, in case OBI's error responses
ever echo back unexpected data.
