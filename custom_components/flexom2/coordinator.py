"""DataUpdateCoordinator for the Flexom 2.0 integration.

Strategy:
  - Open a FlexomClient at setup (REST auth against Ubiant + Hemis).
  - Poll every DEFAULT_SCAN_INTERVAL as a safety net / fallback.
  - Open a STOMP WebSocket to the Hemis building and apply push events live,
    so entities reflect physical actions (wall switch, Flexom app) in <1s.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, MASTER_ZONE_ID
from .flexom_client import FlexomClient, Settings, StompClient, Zone
from .flexom_client.errors import FlexomError

_LOGGER = logging.getLogger(__name__)

_PUSH_EVENT_TYPES = {"ACTUATOR_HARDWARE_STATE", "FACTOR_CURRENT_STATE"}
_STOMP_BACKOFF_SECONDS = (2, 5, 10, 30, 60)


@dataclass
class ZoneSnapshot:
    zone: Zone
    settings: dict[str, Settings] = field(default_factory=dict)


@dataclass
class FlexomData:
    building_id: str
    zones: dict[str, ZoneSnapshot] = field(default_factory=dict)


class FlexomCoordinator(DataUpdateCoordinator[FlexomData]):
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
        self._stomp_task: asyncio.Task | None = None

    async def async_connect(self) -> None:
        self._client = FlexomClient(email=self._email, password=self._password)
        await self._client.__aenter__()
        self._zones_cache = await self._client.get_zones()
        _LOGGER.info(
            "Flexom connected, %d zones on building %s",
            len(self._zones_cache),
            self._client.building.buildingId if self._client.building else "?",
        )
        self._stomp_task = self.hass.loop.create_task(
            self._stomp_keep_alive(), name="flexom2-stomp"
        )

    async def async_disconnect(self) -> None:
        if self._stomp_task is not None:
            self._stomp_task.cancel()
            try:
                await self._stomp_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._stomp_task = None
        if self._client is not None:
            await self._client.__aexit__(None, None, None)
            self._client = None

    async def _async_update_data(self) -> FlexomData:
        if self._client is None or self._client.building is None:
            raise UpdateFailed("Client not connected")

        async def fetch_one(zone: Zone) -> tuple[Zone, dict[str, Settings]] | None:
            if zone.id == MASTER_ZONE_ID:
                return None
            try:
                settings = await self._client.get_zone_settings(zone.id)
            except FlexomError as e:
                _LOGGER.warning("Failed to fetch settings for zone %s: %s", zone.name, e)
                return None
            return zone, settings

        results = await asyncio.gather(*(fetch_one(z) for z in self._zones_cache))
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
        """Set a factor. STOMP will push the real state back within ~1s.

        No optimistic local update: it would lie about shutter position during
        movement and break STOP semantics (click OPEN then STOP would freeze at
        1.0 = re-open instead of current position).
        """
        if self._client is None:
            raise UpdateFailed("Client not connected")
        await self._client.set_zone_factor(zone_id, factor, value)

    async def async_freeze_zone_factor(self, zone_id: str, factor: str) -> None:
        """Send the last STOMP-reported value back as target to halt the motor.

        Used for cover STOP. We use the STOMP-cached value (last event, <200ms lag)
        rather than a fresh REST GET because REST returns the *in-motion* position
        which shifts further during the network round-trip, causing a visible
        flicker before the motor settles on its nearest discrete step.
        """
        if self._client is None:
            raise UpdateFailed("Client not connected")
        snap = self.data.zones.get(zone_id) if self.data else None
        setting = snap.settings.get(factor) if snap else None
        if setting is None:
            # Fallback when the cache has nothing (first boot, race, ...)
            settings = await self._client.get_zone_settings(zone_id)
            setting = settings.get(factor)
            if setting is None:
                return
        await self._client.set_zone_factor(zone_id, factor, setting.value)

    # ----------------------- STOMP plumbing -----------------------

    async def _stomp_keep_alive(self) -> None:
        attempt = 0
        while True:
            try:
                await self._run_stomp_once()
                attempt = 0
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                _LOGGER.warning("STOMP session ended (%s), will retry", e)
            backoff = _STOMP_BACKOFF_SECONDS[
                min(attempt, len(_STOMP_BACKOFF_SECONDS) - 1)
            ]
            attempt += 1
            try:
                await asyncio.sleep(backoff)
            except asyncio.CancelledError:
                raise

    async def _run_stomp_once(self) -> None:
        assert self._client is not None
        await self._client.ensure_auth()
        building = self._client.building
        token = self._client.hemis_token
        if not building or not token:
            raise FlexomError("Missing building or Hemis token for STOMP")
        stomp = StompClient(
            ws_url=building.hemis_stomp_url,
            building_id=building.buildingId,
            token=token,
            handler=self._on_stomp_event,
        )
        await stomp.connect()
        try:
            await stomp.wait_closed()
        finally:
            await stomp.disconnect()

    async def _on_stomp_event(self, event: dict[str, Any]) -> None:
        etype = event.get("type")
        if etype not in _PUSH_EVENT_TYPES:
            return
        zone_id = event.get("zoneId")
        factor = event.get("factorId")
        value_wrap = event.get("value")
        if not zone_id or not factor or not isinstance(value_wrap, dict):
            return
        value = value_wrap.get("value")
        if not isinstance(value, (int, float)):
            return
        if not self.data:
            return
        snap = self.data.zones.get(zone_id)
        if snap is None:
            return
        setting = snap.settings.get(factor)
        if setting is None:
            return
        if setting.value != value:
            _LOGGER.debug(
                "STOMP push: %s/%s %s → %s", snap.zone.name, factor, setting.value, value
            )
            setting.value = float(value)
            self.async_set_updated_data(self.data)
