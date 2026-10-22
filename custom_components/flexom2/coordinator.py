"""DataUpdateCoordinator for the Flexom 2.0 integration.

Strategy:
  - Open a FlexomClient at setup (REST auth against Ubiant + Hemis).
  - Cache the building *structure* (zones + intelligent things) and refresh it
    only when Hemis reports a new ``lastModifiedStructure``.
  - Poll every DEFAULT_SCAN_INTERVAL with 3 cheap calls total
    (all zone settings, all sensors, system infos) as a safety net / fallback.
  - Open a STOMP WebSocket to the Hemis building and apply push events live,
    so entities reflect physical actions (wall switch, Flexom app) in <1s.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_SWITCH_PRESSED,
    FACTOR_BRI,
    FACTOR_BRIEXT,
    FACTOR_SWS,
    IGNORED_SENSOR_FACTORS,
    MASTER_ZONE_ID,
    SIGNAL_SWITCH_PRESSED,
)
from .flexom_client import FlexomClient, Sensor, Settings, StompClient, Thing, Zone
from .flexom_client.errors import FlexomError

_LOGGER = logging.getLogger(__name__)

# Factors whose FACTOR_CURRENT_STATE *is* the controllable state (light on/off, shutter pos).
# TMP is excluded: its current state is the measured temperature, not the setpoint.
_CURRENT_STATE_IS_SETTING = {FACTOR_BRI, FACTOR_BRIEXT}
_STOMP_BACKOFF_SECONDS = (2, 5, 10, 30, 60)


@dataclass
class ZoneSnapshot:
    zone: Zone
    settings: dict[str, Settings] = field(default_factory=dict)
    # Measured values pushed by Hemis (e.g. TMP = room temperature), by factor
    current: dict[str, float] = field(default_factory=dict)


@dataclass
class SensorSnapshot:
    sensor: Sensor
    thing: Thing | None


@dataclass
class FlexomData:
    building_id: str
    zones: dict[str, ZoneSnapshot] = field(default_factory=dict)
    sensors: dict[str, SensorSnapshot] = field(default_factory=dict)  # by sensor id
    things: dict[str, Thing] = field(default_factory=dict)  # by thing id


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
        self._zones_cache: dict[str, Zone] = {}
        self._things_cache: dict[str, Thing] = {}
        self._structure_stamp: int | None = None
        self._switch_last_ts: dict[str, int] = {}
        self._stomp_task: asyncio.Task | None = None
        self.hemis_version: str | None = None

    # ----------------------------------------------------------- lifecycle

    async def async_connect(self) -> None:
        self._client = FlexomClient(
            email=self._email,
            password=self._password,
            session=async_get_clientsession(self.hass),
        )
        await self._client.__aenter__()
        self.hemis_version = self._client.hemis_version
        await self._refresh_structure()
        _LOGGER.info(
            "Flexom connected to Hemis %s: %d zones, %d things on building %s",
            self.hemis_version,
            len(self._zones_cache),
            len(self._things_cache),
            self._client.building.buildingId if self._client.building else "?",
        )
        self._stomp_task = self.hass.loop.create_task(
            self._stomp_keep_alive(), name="flexom2-stomp"
        )

    async def async_disconnect(self) -> None:
        if self._stomp_task is not None:
            self._stomp_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._stomp_task
            self._stomp_task = None
        if self._client is not None:
            await self._client.__aexit__(None, None, None)
            self._client = None

    async def _refresh_structure(self) -> None:
        assert self._client is not None
        zones, things, infos = await asyncio.gather(
            self._client.get_zones(),
            self._client.get_things(),
            self._client.get_infos(),
        )
        self._zones_cache = {z.id: z for z in zones}
        self._things_cache = {t.id: t for t in things}
        self._structure_stamp = infos.lastModifiedStructure

    # -------------------------------------------------------------- polling

    async def _async_update_data(self) -> FlexomData:
        if self._client is None or self._client.building is None:
            raise UpdateFailed("Client not connected")
        try:
            all_settings, sensors, infos = await asyncio.gather(
                self._client.get_all_settings(),
                self._client.get_sensors(),
                self._client.get_infos(),
            )
        except FlexomError as e:
            raise UpdateFailed(f"Flexom poll failed: {e}") from e

        if (
            infos.lastModifiedStructure is not None
            and infos.lastModifiedStructure != self._structure_stamp
        ):
            _LOGGER.info("Hemis structure changed, refreshing zones and things")
            try:
                await self._refresh_structure()
            except FlexomError as e:
                _LOGGER.warning("Structure refresh failed: %s", e)

        previous = self.data
        data = FlexomData(
            building_id=self._client.building.buildingId, things=self._things_cache
        )

        for zone_id, settings in all_settings.items():
            if zone_id == MASTER_ZONE_ID or not settings:
                continue
            zone = self._zones_cache.get(zone_id)
            if zone is None:
                continue
            snap = ZoneSnapshot(zone=zone, settings=settings)
            if previous and (old := previous.zones.get(zone_id)):
                snap.current = dict(old.current)
            data.zones[zone_id] = snap

        for sensor in sensors:
            if sensor.factor in IGNORED_SENSOR_FACTORS:
                continue
            thing = self._lookup_thing(sensor.itId)
            data.sensors[sensor.id] = SensorSnapshot(sensor=sensor, thing=thing)
            if sensor.factor == FACTOR_SWS:
                self._maybe_fire_switch(
                    sensor.id,
                    sensor.raw_value,
                    sensor.timestamp,
                    thing,
                    initial=previous is None,
                )
        return data

    def _lookup_thing(self, it_id: str) -> Thing | None:
        thing = self._things_cache.get(it_id)
        if thing is None and "_" in it_id:
            thing = self._things_cache.get(it_id.split("_", 1)[0])
        return thing

    # -------------------------------------------------------------- actions

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

    # ------------------------------------------------------- switch events

    def _maybe_fire_switch(
        self,
        sensor_id: str,
        value: Any,
        timestamp: int | None,
        thing: Thing | None,
        *,
        initial: bool = False,
    ) -> None:
        """Fire HA events when a wall switch reports a new press (timestamp moved)."""
        if timestamp is None:
            return
        last = self._switch_last_ts.get(sensor_id)
        self._switch_last_ts[sensor_id] = timestamp
        if initial or last is None or timestamp <= last:
            return
        payload = {
            "sensor_id": sensor_id,
            "thing_id": thing.id if thing else None,
            "name": thing.name if thing else sensor_id,
            "zone": thing.zone_name if thing else None,
            "value": value,
            "timestamp": timestamp,
        }
        _LOGGER.debug("Switch press: %s", payload)
        self.hass.bus.async_fire(EVENT_SWITCH_PRESSED, payload)
        async_dispatcher_send(self.hass, SIGNAL_SWITCH_PRESSED.format(sensor_id), payload)

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

    @staticmethod
    def _event_number(event: dict[str, Any]) -> float | None:
        """Hemis sends either ``value: 0.5`` or ``value: {"value": 0.5}`` (or strings)."""
        raw = event.get("value")
        if isinstance(raw, dict):
            raw = raw.get("value")
        if isinstance(raw, bool):
            return None
        if isinstance(raw, (int, float)):
            return float(raw)
        if isinstance(raw, str):
            try:
                return float(raw)
            except ValueError:
                return None
        return None

    async def _on_stomp_event(self, event: dict[str, Any]) -> None:
        if not self.data:
            return
        etype = event.get("type")
        if etype == "SENSOR_STATE":
            self._on_sensor_event(event)
        elif etype in ("ACTUATOR_HARDWARE_STATE", "FACTOR_CURRENT_STATE"):
            self._on_zone_event(event)

    def _on_zone_event(self, event: dict[str, Any]) -> None:
        zone_id = event.get("zoneId")
        factor = event.get("factorId")
        value = self._event_number(event)
        if not zone_id or not factor or value is None:
            return
        snap = self.data.zones.get(zone_id)
        if snap is None:
            return
        changed = False
        if factor in _CURRENT_STATE_IS_SETTING or event.get("type") == "ACTUATOR_HARDWARE_STATE":
            setting = snap.settings.get(factor)
            if setting is not None and setting.value != value:
                _LOGGER.debug(
                    "STOMP push: %s/%s %s → %s", snap.zone.name, factor, setting.value, value
                )
                setting.value = value
                changed = True
        if event.get("type") == "FACTOR_CURRENT_STATE" and snap.current.get(factor) != value:
            snap.current[factor] = value
            changed = True
        if changed:
            self.async_set_updated_data(self.data)

    def _on_sensor_event(self, event: dict[str, Any]) -> None:
        sensor_id = event.get("sensorId")
        factor = event.get("factorId")
        if not sensor_id or not factor or factor in IGNORED_SENSOR_FACTORS:
            return
        snap = self.data.sensors.get(sensor_id)
        raw = event.get("value")
        ts = event.get("timestamp")
        if snap is None:
            # Sensor unknown at last poll (new device): wait for next poll.
            return
        state = snap.sensor.state
        if state.value != raw or state.timestamp != ts:
            state.oldValue = state.value
            state.value = raw
            if isinstance(ts, int):
                state.timestamp = ts
            if factor == FACTOR_SWS:
                self._maybe_fire_switch(
                    sensor_id, raw, ts if isinstance(ts, int) else None, snap.thing
                )
            self.async_set_updated_data(self.data)
