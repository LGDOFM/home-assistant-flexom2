"""DataUpdateCoordinator for the Flexom 2.0 integration.

Responsibilities:
  - Hold a single FlexomClient session for the whole integration lifetime.
  - Fetch zone settings for every zone that exposes BRI/BRIEXT/TMP.
  - Expose a typed snapshot of state to the entity platforms.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, MASTER_ZONE_ID
from .flexom_client import FlexomClient, Settings, Zone
from .flexom_client.errors import FlexomError

_LOGGER = logging.getLogger(__name__)


@dataclass
class ZoneSnapshot:
    """Per-zone data cached by the coordinator."""

    zone: Zone
    settings: dict[str, Settings] = field(default_factory=dict)


@dataclass
class FlexomData:
    """Typed snapshot of the whole building passed to entities."""

    building_id: str
    zones: dict[str, ZoneSnapshot] = field(default_factory=dict)


class FlexomCoordinator(DataUpdateCoordinator[FlexomData]):
    """Coordinator that polls Flexom zones + factors."""

    def __init__(self, hass: HomeAssistant, *, email: str, password: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self._email = email
        self._password = password
        self._client: FlexomClient | None = None
        self._zones_cache: list[Zone] = []

    async def async_connect(self) -> None:
        """Open the Flexom client session once for the integration lifetime."""
        self._client = FlexomClient(email=self._email, password=self._password)
        # Use __aenter__ explicitly so we keep the session open beyond a single block
        await self._client.__aenter__()
        self._zones_cache = await self._client.get_zones()
        _LOGGER.info(
            "Flexom connected, %d zones discovered on building %s",
            len(self._zones_cache),
            self._client.building.buildingId if self._client.building else "?",
        )

    async def async_disconnect(self) -> None:
        if self._client is not None:
            await self._client.__aexit__(None, None, None)
            self._client = None

    async def _async_update_data(self) -> FlexomData:
        if self._client is None or self._client.building is None:
            raise UpdateFailed("Client not connected")

        async def fetch_one(zone):
            if zone.id == MASTER_ZONE_ID:
                return None
            try:
                settings = await self._client.get_zone_settings(zone.id)
            except FlexomError as e:
                _LOGGER.warning("Failed to fetch settings for zone %s: %s", zone.name, e)
                return None
            return zone, settings

        results = await asyncio.gather(
            *(fetch_one(z) for z in self._zones_cache),
            return_exceptions=False,
        )
        data = FlexomData(building_id=self._client.building.buildingId)
        for result in results:
            if result is None:
                continue
            zone, settings = result
            data.zones[zone.id] = ZoneSnapshot(zone=zone, settings=settings)
        return data

    async def async_set_zone_factor(
        self, zone_id: str, factor: str, value: float
    ) -> None:
        """Set a factor and trigger a coordinator refresh so entities update."""
        if self._client is None:
            raise UpdateFailed("Client not connected")
        await self._client.set_zone_factor(zone_id, factor, value)
        # Small grace period, shutters take a moment to start reporting
        await asyncio.sleep(0.5)
        await self.async_request_refresh()
