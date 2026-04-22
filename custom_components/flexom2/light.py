"""Flexom 2.0 light platform — maps the BRI factor to on/off light entities."""
from __future__ import annotations

from typing import Any

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, FACTOR_BRI
from .coordinator import FlexomCoordinator
from .entity import FlexomZoneEntity

# Hardware in user's building is binary relays; brightness dimming is not supported.
# If a future user has dimmable lights, we can detect via Settings.step and extend here.
ON_THRESHOLD = 0.05


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: FlexomCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        FlexomLight(coordinator, zone_id)
        for zone_id, snap in coordinator.data.zones.items()
        if FACTOR_BRI in snap.settings
    ]
    async_add_entities(entities)


class FlexomLight(FlexomZoneEntity, LightEntity):
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_translation_key = "zone_light"

    def __init__(self, coordinator: FlexomCoordinator, zone_id: str) -> None:
        super().__init__(coordinator, zone_id, FACTOR_BRI)
        self._attr_name = "Lumière"

    @property
    def is_on(self) -> bool | None:
        snap = self._snapshot
        if snap is None:
            return None
        setting = snap.settings.get(FACTOR_BRI)
        if setting is None:
            return None
        return setting.value > ON_THRESHOLD

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_zone_factor(self._zone_id, FACTOR_BRI, 1.0)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_zone_factor(self._zone_id, FACTOR_BRI, 0.0)
