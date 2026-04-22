"""Base entity for the Flexom 2.0 integration."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import FlexomCoordinator, ZoneSnapshot

# Label of the "device" per factor (one HA device per zone × factor pair)
_FACTOR_LABEL = {
    "BRI": "Lumière",
    "BRIEXT": "Volet",
    "TMP": "Chauffage",
}


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
        )

    @property
    def _snapshot(self) -> ZoneSnapshot | None:
        return self.coordinator.data.zones.get(self._zone_id)

    @property
    def available(self) -> bool:
        snap = self._snapshot
        return snap is not None and self._factor in snap.settings
