"""End-to-end setup of the integration inside a real Home Assistant core.

Read-only against the building: no command is sent to any device.
"""
from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.flexom2.const import DOMAIN, EVENT_SWITCH_PRESSED

pytestmark = pytest.mark.enable_socket


async def _setup(hass: HomeAssistant, credentials: tuple[str, str]) -> MockConfigEntry:
    email, password = credentials
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Flexom test",
        data={"email": email, "password": password},
        unique_id="test-building",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@pytest.mark.usefixtures("socket_enabled")
async def test_full_setup_and_push(hass: HomeAssistant, credentials: tuple[str, str]) -> None:
    entry = await _setup(hass, credentials)
    coordinator = hass.data[DOMAIN][entry.entry_id]

    states = hass.states.async_all()
    by_domain: dict[str, list] = {}
    for s in states:
        by_domain.setdefault(s.domain, []).append(s)
    counts = {d: len(v) for d, v in sorted(by_domain.items())}
    print("\nentities:", counts)

    assert counts["light"] == 9
    assert counts["cover"] == 4
    assert counts["climate"] == 1
    assert counts["binary_sensor"] == 1
    assert counts["event"] == 16
    assert counts["sensor"] == 13

    # --- names & devices -------------------------------------------------
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    smoke = by_domain["binary_sensor"][0]
    assert smoke.state == "off"
    assert smoke.name == "Détecteur de fumée intelligent Fumée"
    smoke_entry = ent_reg.async_get(smoke.entity_id)
    device = dev_reg.async_get(smoke_entry.device_id)
    assert device.name == "Détecteur de fumée intelligent"
    assert device.manufacturer == "Nexelec"
    assert device.suggested_area == "Entrée Dégagement"

    temp = next(s for s in by_domain["sensor"] if s.attributes.get("factor") == "TMP")
    assert temp.attributes["unit_of_measurement"] == "°C"
    assert temp.attributes["device_class"] == "temperature"
    assert temp.name == "Détecteur de fumée intelligent Température"
    assert 5.0 < float(temp.state) < 40.0

    energy = [s for s in by_domain["sensor"] if s.attributes.get("device_class") == "energy"]
    assert len(energy) == 4  # CPOW x3 (2 on TIC) + HEAT_NRJ
    assert all(s.attributes["state_class"] == "total_increasing" for s in energy)
    tic = sorted(s.name for s in energy if s.name.startswith("Compteur TIC"))
    assert tic == ["Compteur TIC Index électrique 0_C0", "Compteur TIC Index électrique 1_C1"]
    heat = next(s for s in energy if s.attributes.get("factor") == "HEAT_NRJ")
    assert heat.name == "Compteur chauffage Index chauffage"
    assert float(heat.state) > 0

    air = next(
        s for s in by_domain["sensor"] if s.attributes.get("factor") == "AIR_QUALITY_INDEX_NEXELEC"
    )
    assert air.name == "Détecteur de fumée intelligent Qualité de l'air"
    assert air.state  # e.g. OPTIM_AIR

    diag = [s for s in by_domain["sensor"] if s.attributes.get("factor") == "BATTERY_LEVEL"]
    assert ent_reg.async_get(diag[0].entity_id).entity_category == "diagnostic"

    assert not any("SOMFY" in s.name for s in states), "MUTE Somfy thing must be skipped"

    ev = by_domain["event"][0]
    assert ev.state == "unknown"
    assert ev.attributes["event_types"] == [
        "button_0", "button_1", "button_2", "button_3", "button_4", "other",
    ]
    assert ev.name.endswith(" Interrupteur")

    climate = by_domain["climate"][0]
    assert climate.name == "Séjour Chauffage"
    assert climate.attributes["temperature"] == 21.0 or climate.attributes["temperature"] > 5

    # --- STOMP push replay ----------------------------------------------
    data = coordinator.data
    sws_id = next(sid for sid, s in data.sensors.items() if s.sensor.factor == "SWS")
    snap = data.sensors[sws_id]
    ts = (snap.sensor.timestamp or 0) + 1000
    bus_events = []
    hass.bus.async_listen(EVENT_SWITCH_PRESSED, lambda e: bus_events.append(e))

    await coordinator._on_stomp_event(
        {
            "type": "SENSOR_STATE",
            "timestamp": ts,
            "zoneId": snap.thing.zone_id,
            "itId": snap.sensor.itId,
            "value": "2",
            "factorId": "SWS",
            "sensorId": sws_id,
        }
    )
    await hass.async_block_till_done()
    ev_entity_id = ent_reg.async_get_entity_id(
        "event", DOMAIN, f"{data.building_id}_sensor_{sws_id}"
    )
    ev_state = hass.states.get(ev_entity_id)
    assert ev_state.attributes["event_type"] == "button_2"
    assert len(bus_events) == 1
    assert bus_events[0].data["value"] == "2"
    assert bus_events[0].data["name"] == snap.thing.name

    await coordinator._on_stomp_event(
        {
            "type": "FACTOR_CURRENT_STATE",
            "zoneId": "sjour_4xsgtq9k",
            "factorId": "TMP",
            "value": 22.4,
        }
    )
    await hass.async_block_till_done()
    assert hass.states.get(climate.entity_id).attributes["current_temperature"] == 22.4

    await coordinator._on_stomp_event(
        {"type": "FACTOR_CURRENT_STATE", "zoneId": "wc_4aws0q8l", "factorId": "BRI", "value": 1.0}
    )
    await hass.async_block_till_done()
    wc = next(s for s in hass.states.async_all("light") if s.name == "WC Lumière")
    assert wc.state == "on"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
