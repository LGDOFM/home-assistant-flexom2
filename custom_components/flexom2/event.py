"""Flexom 2.0 event platform — wall switch presses.

Every EnOcean wall switch (VIMAR Plana) exposes an ``SWS`` sensor whose value
is the last pressed rocker position and whose timestamp moves on each press.
The coordinator turns a timestamp change into a dispatcher signal (and a
``flexom2_switch_pressed`` bus event); this entity surfaces it as an HA event
entity so it can be used directly as an automation trigger.

Values observed on the real hardware (EEP F6-02-01), 22/10/2026:
  single rocker : 2 = top, 1 = bottom, 0 = released
  double rocker : 4 = top left, 3 = bottom left, 2 = top right, 1 = bottom right
The value is the physical position, NOT the function: depending on the wiring
"top" may switch a light on or off.
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
from .flexom_client import Thing

EVENT_RELEASED = "released"
EVENT_OTHER = "other"

_SINGLE_ROCKER = {"0": EVENT_RELEASED, "1": "bottom", "2": "top"}
_DOUBLE_ROCKER = {
    "0": EVENT_RELEASED,
    "1": "bottom_right",
    "2": "top_right",
    "3": "bottom_left",
    "4": "top_left",
}

EVENT_TYPES_SINGLE = ["top", "bottom", EVENT_RELEASED, EVENT_OTHER]
EVENT_TYPES_DOUBLE = [
    "top_left",
    "bottom_left",
    "top_right",
    "bottom_right",
    EVENT_RELEASED,
    EVENT_OTHER,
]


def _is_double_rocker(thing: Thing | None) -> bool:
    """Detect 4-button switches from Hemis' hardware customisation, else from the model."""
    if thing is None:
        return True
    for hw in (thing.model_extra or {}).get("hardwareCustomizations") or []:
        for desc in hw.get("descriptions") or []:
            if desc.get("name") == "SEL_SWS_REP":
                return str(desc.get("value", "")).upper() != "SWS_2_BTN"
    model = (thing.model or "").upper()
    return "1001" not in model  # VITA1001 = single rocker, VITA1002 = double


def _event_type(value: Any, double: bool) -> str:
    if value is None:
        return EVENT_OTHER
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    table = _DOUBLE_ROCKER if double else _SINGLE_ROCKER
    return table.get(text, EVENT_OTHER)


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
    _attr_translation_key = "switch"

    def __init__(self, coordinator: FlexomCoordinator, sensor_id: str) -> None:
        super().__init__(coordinator, sensor_id)
        snap = coordinator.data.sensors[sensor_id]
        self._double = _is_double_rocker(snap.thing)
        self._attr_event_types = EVENT_TYPES_DOUBLE if self._double else EVENT_TYPES_SINGLE

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
            _event_type(value, self._double),
            {"value": value, "timestamp": payload.get("timestamp")},
        )
        self.async_write_ha_state()
