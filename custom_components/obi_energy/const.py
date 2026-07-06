"""Constants for the OBI Energy integration."""
from __future__ import annotations

DOMAIN = "obi_energy"

# Config entry / options keys
CONF_HH_ID = "hh_id"
CONF_MID_ID = "mid_id"
CONF_HISTORICAL_DURATION = "historical_duration"
CONF_LOGIN_REFRESH_INTERVAL = "login_refresh_interval"
CONF_LIVE_ENABLED = "live_enabled"
CONF_DEBUG = "debug"

# Defaults
DEFAULT_SCAN_INTERVAL = 60  # seconds
DEFAULT_LOGIN_REFRESH_INTERVAL = 55 * 60  # seconds
DEFAULT_HISTORICAL_DURATION = "PT6H"
DEFAULT_LIVE_ENABLED = False
LIVE_UPLOAD_INTERVAL_ENABLED = 2  # seconds
LIVE_UPLOAD_INTERVAL_DISABLED = 300  # seconds
DEFAULT_DEBUG = False

# API
LOGIN_URL = "https://www.obi.de/regi/auth/api/public/login"
API_BASE_URL = "https://energy-tracking-backend.prod-eks.dbs.obi.solutions"
BRIDGES_URL = f"{API_BASE_URL}/bridges"
HISTORICAL_DATA_URL_TEMPLATE = API_BASE_URL + "/historical-data/{hh_id}/{mid_id}/meter"
SENSOR_URL_TEMPLATE = API_BASE_URL + "/sensors/{mid_id}"
LIVE_DATA_URL = "wss://energy-tracking-livemode.prod-eks.dbs.obi.solutions/retrieving"

API_KEY = "Rh57q3vtOPYTf6FtArVN1boy2AyEiIqaGEmnMks7"
USER_AGENT = "heyOBI APP / iPhone17,2 / 4.9.1 / 560"
LIVE_USER_AGENT = "app_client"
ACCEPT_LANGUAGE = "de-DE,de;q=0.9"
LOGIN_COOKIE = "obi_storeid=527"
LOGIN_HOST = "www.obi.de"
LOGIN_ORIGIN = "https://www.obi.de"
LOGIN_REFERER = "https://www.obi.de/"
LOGIN_COUNTRY = "de"
ACCEPT_BRIDGES = "application/vnd.obi.companion.energy-tracking.bridge.v1+json"
ACCEPT_HISTORICAL = "application/vnd.obi.companion.energy-tracking.historical-record.v1+json"
ACCEPT_SENSOR = "application/vnd.obi.companion.energy-tracking.sensor.v1+json"

MEASURE_ENERGY = "energy"
MEASURE_NEGATIVE_ENERGY = "negative_energy"

WH_PER_KWH = 1000
