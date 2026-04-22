"""Flexom 2.0 climate platform — maps the TMP factor to a thermostat entity."""
from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, FACTOR_TMP
from .coordinator import FlexomCoordinator
from .entity import FlexomZoneEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: FlexomCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        FlexomClimate(coordinator, zone_id)
        for zone_id, snap in coordinator.data.zones.items()
        if FACTOR_TMP in snap.settings
    ]
    async_add_entities(entities)


class FlexomClimate(FlexomZoneEntity, ClimateEntity):
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT]
    _attr_hvac_mode = HVACMode.HEAT
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_translation_key = "zone_climate"

    def __init__(self, coordinator: FlexomCoordinator, zone_id: str) -> None:
        super().__init__(coordinator, zone_id, FACTOR_TMP)

    @property
    def target_temperature(self) -> float | None:
        snap = self._snapshot
        if snap is None:
            return None
        setting = snap.settings.get(FACTOR_TMP)
        return None if setting is None else setting.value

    @property
    def min_temp(self) -> float:
        snap = self._snapshot
        if snap is not None and (s := snap.settings.get(FACTOR_TMP)) and s.min is not None:
            return s.min
        return 7.0

    @property
    def max_temp(self) -> float:
        snap = self._snapshot
        if snap is not None and (s := snap.settings.get(FACTOR_TMP)) and s.max is not None:
            return s.max
        return 35.0

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        await self.coordinator.async_set_zone_factor(self._zone_id, FACTOR_TMP, float(temp))

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        # Flexom doesn't expose HVAC mode switching via the TMP factor — always "heat"
        return
