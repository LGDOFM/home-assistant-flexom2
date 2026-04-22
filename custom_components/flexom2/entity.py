"""Base entity for the Flexom 2.0 integration."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import FlexomCoordinator, ZoneSnapshot


class FlexomZoneEntity(CoordinatorEntity[FlexomCoordinator]):
    """Base for entities tied to a single Flexom zone + factor."""

    _attr_has_entity_name = True

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
        self._attr_unique_id = f"{building_id}_{zone_id}_{factor}"
        # Group all entities of a zone under one device
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{building_id}_{zone_id}")},
            name=snap.zone.name,
            manufacturer="Flexom / Ubiant",
            model=snap.zone.type or "Zone",
        )

    @property
    def _snapshot(self) -> ZoneSnapshot | None:
        return self.coordinator.data.zones.get(self._zone_id)

    @property
    def available(self) -> bool:
        snap = self._snapshot
        return snap is not None and self._factor in snap.settings
