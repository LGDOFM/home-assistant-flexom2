"""Flexom 2.0 sensor platform — exposes intelligent-thing sensors.

Covers the Nexelec smoke detector (temperature, humidity, air quality, battery,
maintenance counters) and the EWATTCH energy meters (electricity / heating /
hot-water indexes). Unknown factors fall back to a generic sensor so nothing
is silently dropped.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfEnergy,
    UnitOfTemperature,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import (
    DOMAIN,
    FACTOR_AIR_QUALITY,
    FACTOR_BATTERY,
    FACTOR_CPOW,
    FACTOR_HEAT_NRJ,
    FACTOR_HOTWATER_INDEX,
    FACTOR_HUM,
    FACTOR_HYGRO_COMFORT,
    FACTOR_IPOW,
    FACTOR_REMAINING_LIFETIME,
    FACTOR_SMOKE,
    FACTOR_SWS,
    FACTOR_TIME_SINCE_MAINTENANCE,
    FACTOR_TMP,
)
from .coordinator import FlexomCoordinator
from .entity import FlexomThingEntity
from .flexom_client import Sensor

# Factors handled by other platforms
_OTHER_PLATFORMS = {FACTOR_SMOKE, FACTOR_SWS}


def _numeric(sensor: Sensor) -> StateType:
    return sensor.numeric_value


def _raw(sensor: Sensor) -> StateType:
    v = sensor.raw_value
    return None if v is None else str(v)


@dataclass(frozen=True, kw_only=True)
class FlexomSensorDescription(SensorEntityDescription):
    value_fn: Callable[[Sensor], StateType] = _numeric


SENSOR_DESCRIPTIONS: dict[str, FlexomSensorDescription] = {
    FACTOR_TMP: FlexomSensorDescription(
        key=FACTOR_TMP,
        translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    FACTOR_HUM: FlexomSensorDescription(
        key=FACTOR_HUM,
        translation_key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    FACTOR_CPOW: FlexomSensorDescription(
        key=FACTOR_CPOW,
        translation_key="electricity_index",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
    ),
    FACTOR_HEAT_NRJ: FlexomSensorDescription(
        key=FACTOR_HEAT_NRJ,
        translation_key="heating_index",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
    ),
    FACTOR_HOTWATER_INDEX: FlexomSensorDescription(
        key=FACTOR_HOTWATER_INDEX,
        translation_key="hot_water_index",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=3,
    ),
    FACTOR_IPOW: FlexomSensorDescription(
        # Hemis documents IPOW as "apparent power" but reports it with a Wh unit;
        # exposed as a plain measurement until a real value shows up to validate.
        key=FACTOR_IPOW,
        translation_key="apparent_power",
        icon="mdi:flash",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    FACTOR_BATTERY: FlexomSensorDescription(
        # Raw EnOcean "energy storage" level as reported by Hemis (1.0 = full).
        key=FACTOR_BATTERY,
        translation_key="battery_level",
        icon="mdi:battery",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    FACTOR_AIR_QUALITY: FlexomSensorDescription(
        key=FACTOR_AIR_QUALITY,
        translation_key="air_quality",
        icon="mdi:air-filter",
        value_fn=_raw,
    ),
    FACTOR_HYGRO_COMFORT: FlexomSensorDescription(
        key=FACTOR_HYGRO_COMFORT,
        translation_key="hygrothermal_comfort",
        icon="mdi:home-thermometer",
        value_fn=_raw,
    ),
    FACTOR_REMAINING_LIFETIME: FlexomSensorDescription(
        key=FACTOR_REMAINING_LIFETIME,
        translation_key="remaining_lifetime",
        icon="mdi:calendar-clock",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    FACTOR_TIME_SINCE_MAINTENANCE: FlexomSensorDescription(
        key=FACTOR_TIME_SINCE_MAINTENANCE,
        translation_key="time_since_maintenance",
        icon="mdi:wrench-clock",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
}


def _generic_description(factor: str) -> FlexomSensorDescription:
    return FlexomSensorDescription(
        key=factor,
        name=factor.replace("_", " ").title(),
        icon="mdi:eye",
        value_fn=_raw,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: FlexomCoordinator = hass.data[DOMAIN][entry.entry_id]
    # Disambiguate names when one thing has several sensors of the same factor
    # (e.g. the TIC meter exposes two CPOW channels).
    dup = Counter(
        (snap.sensor.itId, snap.sensor.factor)
        for snap in coordinator.data.sensors.values()
    )
    entities: list[FlexomSensor] = []
    for sensor_id, snap in coordinator.data.sensors.items():
        factor = snap.sensor.factor
        if factor in _OTHER_PLATFORMS:
            continue
        if snap.thing is not None and snap.thing.is_mute:
            continue
        description = SENSOR_DESCRIPTIONS.get(factor) or _generic_description(factor)
        suffix = sensor_id.split("#")[-1] if dup[(snap.sensor.itId, factor)] > 1 else None
        entities.append(FlexomSensor(coordinator, sensor_id, description, suffix))
    async_add_entities(entities)


class FlexomSensor(FlexomThingEntity, SensorEntity):
    entity_description: FlexomSensorDescription

    def __init__(
        self,
        coordinator: FlexomCoordinator,
        sensor_id: str,
        description: FlexomSensorDescription,
        suffix: str | None,
    ) -> None:
        super().__init__(coordinator, sensor_id)
        self.entity_description = description
        if suffix:
            self._attr_translation_placeholders = {"channel": suffix}
            self._attr_translation_key = (
                f"{description.translation_key}_channel" if description.translation_key else None
            )
            if description.translation_key is None:
                self._attr_name = f"{description.name} {suffix}"

    @property
    def native_value(self) -> StateType:
        snap = self._snapshot
        if snap is None:
            return None
        return self.entity_description.value_fn(snap.sensor)
