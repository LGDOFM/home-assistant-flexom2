"""Flexom 2.0 cover platform — maps the BRIEXT factor to shutter entities."""
from __future__ import annotations

from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, FACTOR_BRIEXT
from .coordinator import FlexomCoordinator
from .entity import FlexomZoneEntity

CLOSED_THRESHOLD = 0.05


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: FlexomCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        FlexomCover(coordinator, zone_id)
        for zone_id, snap in coordinator.data.zones.items()
        if FACTOR_BRIEXT in snap.settings
    ]
    async_add_entities(entities)


class FlexomCover(FlexomZoneEntity, CoverEntity):
    _attr_device_class = CoverDeviceClass.SHUTTER
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.SET_POSITION
        | CoverEntityFeature.STOP
    )
    _attr_translation_key = "zone_cover"

    def __init__(self, coordinator: FlexomCoordinator, zone_id: str) -> None:
        super().__init__(coordinator, zone_id, FACTOR_BRIEXT)

    @property
    def current_cover_position(self) -> int | None:
        snap = self._snapshot
        if snap is None:
            return None
        setting = snap.settings.get(FACTOR_BRIEXT)
        if setting is None:
            return None
        return round(setting.value * 100)

    @property
    def is_closed(self) -> bool | None:
        pos = self.current_cover_position
        if pos is None:
            return None
        return pos < CLOSED_THRESHOLD * 100

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_zone_factor(self._zone_id, FACTOR_BRIEXT, 1.0)

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_zone_factor(self._zone_id, FACTOR_BRIEXT, 0.0)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        position = kwargs[ATTR_POSITION]
        await self.coordinator.async_set_zone_factor(
            self._zone_id, FACTOR_BRIEXT, position / 100.0
        )

    async def async_stop_cover(self, **kwargs: Any) -> None:
        # Flexom has no documented STOP; re-send the current cached position
        # so the target equals the current, which typically freezes the motor.
        pos = self.current_cover_position
        if pos is None:
            return
        await self.coordinator.async_set_zone_factor(
            self._zone_id, FACTOR_BRIEXT, pos / 100.0
        )
