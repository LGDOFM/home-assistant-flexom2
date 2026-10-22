"""Flexom 2.0 event platform — wall switch presses.

Every EnOcean wall switch (VIMAR Plana) exposes an ``SWS`` sensor whose value
is the last pressed button id and whose timestamp moves on each press. The
coordinator turns a timestamp change into a dispatcher signal (and a
``flexom2_switch_pressed`` bus event); this entity surfaces it as an HA event
entity so it can be used directly as an automation trigger.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, FACTOR_SWS, SIGNAL_SWITCH_PRESSED
from .coordinator import FlexomCoordinator
from .entity import FlexomThingEntity

# Observed SWS values on EEP F6-02-01 rockers: 0 = release / none, 1-4 = button id.
_KNOWN_BUTTONS = ("0", "1", "2", "3", "4")
EVENT_TYPES = [f"button_{b}" for b in _KNOWN_BUTTONS] + ["other"]


def _event_type(value: Any) -> str:
    if value is None:
        return "other"
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return f"button_{text}" if text in _KNOWN_BUTTONS else "other"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: FlexomCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        FlexomSwitchEvent(coordinator, sensor_id)
        for sensor_id, snap in coordinator.data.sensors.items()
        if snap.sensor.factor == FACTOR_SWS
        and not (snap.thing is not None and snap.thing.is_mute)
    ]
    async_add_entities(entities)


class FlexomSwitchEvent(FlexomThingEntity, EventEntity):
    _attr_device_class = EventDeviceClass.BUTTON
    _attr_event_types = EVENT_TYPES
    _attr_translation_key = "switch"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_SWITCH_PRESSED.format(self._sensor_id),
                self._handle_press,
            )
        )

    @callback
    def _handle_press(self, payload: dict[str, Any]) -> None:
        value = payload.get("value")
        self._trigger_event(
            _event_type(value),
            {"value": value, "timestamp": payload.get("timestamp")},
        )
        self.async_write_ha_state()
