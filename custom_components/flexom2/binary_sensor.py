"""Flexom 2.0 binary sensor platform — smoke detectors."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, FACTOR_SMOKE
from .coordinator import FlexomCoordinator
from .entity import FlexomThingEntity

_TRUE_VALUES = {"1", "true", "on", "alarm"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: FlexomCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        FlexomSmokeSensor(coordinator, sensor_id)
        for sensor_id, snap in coordinator.data.sensors.items()
        if snap.sensor.factor == FACTOR_SMOKE
        and not (snap.thing is not None and snap.thing.is_mute)
    ]
    async_add_entities(entities)


class FlexomSmokeSensor(FlexomThingEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.SMOKE
    _attr_translation_key = "smoke"

    @property
    def is_on(self) -> bool | None:
        snap = self._snapshot
        if snap is None:
            return None
        raw = snap.sensor.raw_value
        if raw is None:
            return None
        if isinstance(raw, (int, float)):
            return raw > 0
        return str(raw).strip().lower() in _TRUE_VALUES
