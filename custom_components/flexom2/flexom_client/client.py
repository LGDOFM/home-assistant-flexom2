from __future__ import annotations

import logging
from types import TracebackType

import aiohttp

from .errors import FlexomError
from .hemis import HemisService
from .models import Building, HemisUser, Settings, Thing, UbiantUser, Zone
from .ubiant import UbiantService

_log = logging.getLogger(__name__)


class FlexomClient:
    """Async façade orchestrating Ubiant (account/buildings) + Hemis (smart home).

    Usage:
        async with FlexomClient(email=..., password=...) as client:
            zones = await client.get_zones()
    """

    def __init__(self, email: str, password: str, *, building_index: int = 0):
        self._email = email
        self._password = password
        self._building_index = building_index
        self._session: aiohttp.ClientSession | None = None
        self._ubiant: UbiantService | None = None
        self._hemis: HemisService | None = None
        self._building: Building | None = None
        self._ubiant_user: UbiantUser | None = None
        self._hemis_user: HemisUser | None = None

    async def __aenter__(self) -> FlexomClient:
        self._session = aiohttp.ClientSession()
        self._ubiant = UbiantService(self._session)
        try:
            await self._connect()
        except BaseException:
            await self._session.close()
            self._session = None
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    @property
    def building(self) -> Building | None:
        return self._building

    @property
    def ubiant_user(self) -> UbiantUser | None:
        return self._ubiant_user

    async def _connect(self) -> None:
        assert self._ubiant is not None and self._session is not None
        self._ubiant_user = await self._ubiant.login(self._email, self._password)
        buildings = await self._ubiant.get_buildings()
        if not buildings:
            raise FlexomError("No building found on this Ubiant account")
        if self._building_index >= len(buildings):
            raise FlexomError(
                f"building_index={self._building_index} out of range "
                f"(account has {len(buildings)} building(s))"
            )
        self._building = buildings[self._building_index]
        _log.info("Selected building: %s", self._building.nickname or self._building.buildingId)
        self._hemis = HemisService(
            base_url=self._building.hemis_base_url,
            user_id=self._ubiant_user.id,
            session=self._session,
        )
        self._hemis_user = await self._hemis.login(
            email=self._ubiant_user.email,
            auth_token=self._building.authorizationToken,
            kernel_id=self._building.kernel_slot,
        )

    async def _ensure_auth(self) -> None:
        assert self._ubiant is not None and self._hemis is not None
        if self._ubiant.is_token_valid():
            return
        _log.info("Token expiring soon, re-authenticating")
        self._ubiant_user = await self._ubiant.login(self._email, self._password)
        assert self._building is not None and self._ubiant_user is not None
        self._hemis_user = await self._hemis.login(
            email=self._ubiant_user.email,
            auth_token=self._building.authorizationToken,
            kernel_id=self._building.kernel_slot,
        )

    async def get_zones(self) -> list[Zone]:
        await self._ensure_auth()
        assert self._hemis is not None
        return await self._hemis.get_zones()

    async def get_zone_settings(self, zone_id: str) -> dict[str, Settings]:
        await self._ensure_auth()
        assert self._hemis is not None
        return await self._hemis.get_zone_settings(zone_id)

    async def get_things(self) -> list[Thing]:
        await self._ensure_auth()
        assert self._hemis is not None
        return await self._hemis.get_things()

    async def set_zone_factor(self, zone_id: str, factor: str, value: float) -> None:
        await self._ensure_auth()
        assert self._hemis is not None
        await self._hemis.set_zone_factor(zone_id, factor, value)
