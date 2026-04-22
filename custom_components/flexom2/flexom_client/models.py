from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Factor = Literal["BRI", "BRIEXT", "TMP"]

MASTER_ZONE_ID = "MyHemis"


class _LaxModel(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class UbiantUser(_LaxModel):
    id: str
    email: str
    token: str


class BuildingAddress(_LaxModel):
    city: str | None = None
    street_name: str | None = None
    formatted_address: str | None = None


class BuildingOwner(_LaxModel):
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    user_id: str | None = None


class Building(_LaxModel):
    buildingId: str
    hemis_base_url: str
    hemis_stomp_url: str
    authorizationToken: str
    kernel_slot: str
    nickname: str | None = None
    timezone: str | None = None
    address: BuildingAddress | None = None
    owner: BuildingOwner | None = None
    is_connected: bool | None = None


class HemisUser(_LaxModel):
    token: str
    hemisVersion: str | None = None
    offset: int | None = None
    permissions: list[str] = Field(default_factory=list)
    role: str | None = None
    timeZone: str | None = None
    stompEnabled: bool | None = None


class Settings(_LaxModel):
    value: float
    min: float | None = None
    max: float | None = None
    step: float | None = None
    unit: str | None = None
    actuatorCount: int | None = None


class Zone(_LaxModel):
    id: str
    name: str
    parentId: str | None = None
    surface: str | None = None
    type: str | None = None
    settings: dict[str, Settings] = Field(default_factory=dict)


class ThingTypeInformation(_LaxModel):
    id: str
    name: str
    protocol: str | None = None
    hasActuators: bool | None = None
    hasSensors: bool | None = None
    actuatorsFactors: dict[str, list[str]] = Field(default_factory=dict)
    sensorsFactor: dict[str, str] = Field(default_factory=dict)


class Thing(_LaxModel):
    id: str
    name: str
    externalId: str | None = None
    comID: str | None = None
    firmwareVersion: str | None = None
    zoneInformation: Zone | None = None
    typeInformation: ThingTypeInformation | None = None
    state: str | None = None
    rssi: int | None = None
