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
    label: str | None = None
    description: str | None = None
    timezone: str | None = None
    address: BuildingAddress | None = None
    owner: BuildingOwner | None = None
    is_connected: bool | None = None
    server_region: str | None = None
    kernel_state: str | None = None
    building_brand: str | None = None
    auth_hemis_level: str | None = None
    project: str | None = None


class HemisUser(_LaxModel):
    token: str
    hemisVersion: str | None = None
    offset: int | None = None
    permissions: list[str] = Field(default_factory=list)
    role: str | None = None
    timeZone: str | None = None
    stompEnabled: bool | None = None


class HemisStatus(_LaxModel):
    """GET /WS_SystemManagement/status"""

    hemis_version: str | None = None
    git_commit: str | None = None


class HemisInfos(_LaxModel):
    """GET /WS_SystemManagement/infos.

    ``lastModifiedStructure`` changes whenever zones / things are edited in the
    installer tools, so it is a cheap signal to refresh the structure caches.
    """

    kernelId: str | None = None
    status: str | None = None
    buildingId: str | None = None
    startDate: int | None = None
    lastModifiedStructure: int | None = None


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
    metazone: bool | None = None
    settings: dict[str, Settings] = Field(default_factory=dict)


class ThingTypeInformation(_LaxModel):
    id: str
    name: str
    protocol: str | None = None
    category: str | None = None
    hasActuators: bool | None = None
    hasSensors: bool | None = None
    actuatorsFactors: dict[str, list[str]] = Field(default_factory=dict)
    sensorsFactor: dict[str, str] = Field(default_factory=dict)


class Thing(_LaxModel):
    """An intelligent thing (physical device) as returned by /intelligent-things/listV2."""

    id: str
    name: str
    externalId: str | None = None
    comID: str | None = None
    firmwareVersion: str | None = None
    zoneInformation: Zone | None = None
    typeInformation: ThingTypeInformation | None = None
    state: str | None = None  # OK / PAIRED / MUTE / ...
    rssi: int | None = None

    @property
    def zone_id(self) -> str | None:
        return self.zoneInformation.id if self.zoneInformation else None

    @property
    def zone_name(self) -> str | None:
        return self.zoneInformation.name if self.zoneInformation else None

    @property
    def model(self) -> str | None:
        return self.typeInformation.name if self.typeInformation else None

    @property
    def is_mute(self) -> bool:
        return (self.state or "").upper() == "MUTE"


class SensorState(_LaxModel):
    """Current state of a sensor. ``id`` is the factor id (TMP, HUM, SWS, SMOKE, CPOW...)."""

    id: str
    value: str | float | int | None = None
    timestamp: int | None = None
    oldValue: str | float | int | None = None
    evol: str | None = None  # INC / DEC / SAME


class Sensor(_LaxModel):
    """A sensor as returned by GET /intelligent-things/sensors."""

    id: str
    itId: str
    state: SensorState
    activated: bool | None = None
    usableByUser: bool | None = None

    @property
    def factor(self) -> str:
        return self.state.id

    @property
    def raw_value(self) -> str | float | int | None:
        return self.state.value

    @property
    def numeric_value(self) -> float | None:
        v = self.state.value
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    @property
    def timestamp(self) -> int | None:
        return self.state.timestamp


class ActuatorState(_LaxModel):
    itId: str | None = None
    actuatorId: str | None = None
    value: float | None = None
    timeStamp: int | None = None
    minActionValue: float | None = None
    maxActionValue: float | None = None
    progressive: bool | None = None


class Actuator(_LaxModel):
    """An actuator as returned by GET /intelligent-things/actuators.

    - ``state``: last target applied by Hemis
    - ``hardwareState``: last value reported by the hardware itself
    - ``targetState``: pending target (if any)
    """

    actuatorId: str
    itId: str
    state: ActuatorState | None = None
    hardwareState: ActuatorState | None = None
    targetState: ActuatorState | None = None
    factors: list[str] = Field(default_factory=list)
    actionningRepresentation: str | None = None
    activated: bool | None = None
    usableByUser: bool | None = None

    @property
    def factor(self) -> str | None:
        return self.factors[0] if self.factors else None

    @property
    def value(self) -> float | None:
        return self.state.value if self.state else None

    @property
    def hardware_value(self) -> float | None:
        return self.hardwareState.value if self.hardwareState else None
