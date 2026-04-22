"""Constants for the Flexom 2.0 integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "flexom2"

CONF_EMAIL = "email"
CONF_PASSWORD = "password"

DEFAULT_SCAN_INTERVAL = timedelta(seconds=60)
MIN_SCAN_INTERVAL = timedelta(seconds=30)

FACTOR_BRI = "BRI"
FACTOR_BRIEXT = "BRIEXT"
FACTOR_TMP = "TMP"

# Flexom's MyHemis zone is a virtual container for the whole building — skip it for entities
MASTER_ZONE_ID = "MyHemis"
