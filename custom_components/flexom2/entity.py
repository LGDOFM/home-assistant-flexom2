"""Base entities for the Flexom 2.0 integration."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MASTER_ZONE_ID
from .coordinator import FlexomCoordinator, SensorSnapshot, ZoneSnapshot
from .flexom_client import Thing

# Label of the "device" per factor (one HA device per zone × factor pair)
_FACTOR_LABEL = {
    "BRI": "Lumière",
    "BRIEXT": "Volet",
    "TMP": "Chauffage",
}


def _manufacturer(thing: Thing) -> str:
    model = thing.model or ""
    return model.split(" ", 1)[0] if model else "Flexom / Ubiant"


class FlexomZoneEntity(CoordinatorEntity[FlexomCoordinator]):
    """Base for entities tied to a single Flexom zone + factor.

    Each (zone, factor) pair is exposed as its own HA device so "Chambre 1 Volet"
    and "Chambre 1 Lumière" appear as distinct devices in the UI.
    """

    _attr_has_entity_name = True
    _attr_name = None  # use device name directly (no "Chambre 1 Volet Volet")

    def __init__(
        self,
        coordinator: FlexomCoordinator,
        zone_id: str,
        factor: str,
    ) -> None:
        super().__init__(coordinator)
        self._zone_id = zone_id
        self._factor = factor
        snap = coordinator.data.zones[zone_id]
        building_id = coordinator.data.building_id
        label = _FACTOR_LABEL.get(factor, factor)
        self._attr_unique_id = f"{building_id}_{zone_id}_{factor}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{building_id}_{zone_id}_{factor}")},
            name=f"{snap.zone.name} {label}",
            manufacturer="Flexom / Ubiant",
            model=label,
            suggested_area=snap.zone.name,
            sw_version=coordinator.hemis_version,
        )

    @property
    def _snapshot(self) -> ZoneSnapshot | None:
        return self.coordinator.data.zones.get(self._zone_id)

    @property
    def available(self) -> bool:
        snap = self._snapshot
        return snap is not None and self._factor in snap.settings


class FlexomThingEntity(CoordinatorEntity[FlexomCoordinator]):
    """Base for entities tied to one sensor of an intelligent thing.

    One HA device per physical thing (smoke detector, wall switch, meter...),
    holding every sensor entity that thing exposes.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: FlexomCoordinator,
        sensor_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._sensor_id = sensor_id
        snap = coordinator.data.sensors[sensor_id]
        thing = snap.thing
        building_id = coordinator.data.building_id
        self._attr_unique_id = f"{building_id}_sensor_{sensor_id}"
        if thing is not None:
            area = thing.zone_name if thing.zone_id != MASTER_ZONE_ID else None
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, f"{building_id}_thing_{thing.id}")},
                name=thing.name,
                manufacturer=_manufacturer(thing),
                model=thing.model,
                suggested_area=area,
                sw_version=thing.firmwareVersion or None,
            )
        else:
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, f"{building_id}_thing_{snap.sensor.itId}")},
                name=snap.sensor.itId,
                manufacturer="Flexom / Ubiant",
            )

    @property
    def _snapshot(self) -> SensorSnapshot | None:
        return self.coordinator.data.sensors.get(self._sensor_id)

    @property
    def available(self) -> bool:
        snap = self._snapshot
        if snap is None:
            return False
        return not (snap.thing is not None and snap.thing.is_mute)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        snap = self._snapshot
        if snap is None:
            return {}
        attrs: dict[str, object] = {
            "factor": snap.sensor.factor,
            "sensor_id": snap.sensor.id,
            "thing_id": snap.sensor.itId,
        }
        if snap.sensor.timestamp:
            attrs["last_update_ts"] = snap.sensor.timestamp
        if snap.thing is not None:
            attrs["zone"] = snap.thing.zone_name
            attrs["device_state"] = snap.thing.state
        return attrs
