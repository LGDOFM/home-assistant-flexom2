"""Constants for the Flexom 2.0 integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "flexom2"

CONF_EMAIL = "email"
CONF_PASSWORD = "password"

DEFAULT_SCAN_INTERVAL = timedelta(seconds=30)
MIN_SCAN_INTERVAL = timedelta(seconds=15)

# Zone factors (controllable)
FACTOR_BRI = "BRI"
FACTOR_BRIEXT = "BRIEXT"
FACTOR_TMP = "TMP"

# Sensor factors (read-only, per intelligent thing)
FACTOR_SWS = "SWS"  # wall switch press
FACTOR_SMOKE = "SMOKE"
FACTOR_HUM = "HUM"
FACTOR_CPOW = "CPOW"  # electricity index (kWh)
FACTOR_HEAT_NRJ = "HEAT_NRJ"  # heating index (kWh)
FACTOR_HOTWATER_INDEX = "HOTWATER_INDEX"  # hot water index (m3)
FACTOR_IPOW = "IPOW"  # apparent power
FACTOR_BATTERY = "BATTERY_LEVEL"
FACTOR_AIR_QUALITY = "AIR_QUALITY_INDEX_NEXELEC"
FACTOR_HYGRO_COMFORT = "HYGROTHERMAL_COMFORT_INDEX_NEXELEC"
FACTOR_REMAINING_LIFETIME = "REMAINING_PRODUCT_LIFETIME"
FACTOR_TIME_SINCE_MAINTENANCE = "TIME_SINCE_LAST_MAINTENANCE"

# Sensor factors that are plumbing, never exposed as entities
IGNORED_SENSOR_FACTORS = {"REPEATER", "OCC"}

# Flexom's MyHemis zone is a virtual container for the whole building — skip it for entities
MASTER_ZONE_ID = "MyHemis"

# Event bus
EVENT_SWITCH_PRESSED = f"{DOMAIN}_switch_pressed"
SIGNAL_SWITCH_PRESSED = f"{DOMAIN}_switch_pressed_{{}}"  # .format(sensor_id)
SIGNAL_STRUCTURE_CHANGED = f"{DOMAIN}_structure_changed"
