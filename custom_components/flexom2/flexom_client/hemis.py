from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .errors import FlexomAuthError, FlexomNetworkError, FlexomRateLimitError
from .models import (
    MASTER_ZONE_ID,
    Actuator,
    HemisInfos,
    HemisStatus,
    HemisUser,
    Sensor,
    Settings,
    Thing,
    Zone,
)

_log = logging.getLogger(__name__)


class HemisService:
    """REST client for one Hemis (building) instance.

    Hemis is a per-building server; its base URL comes from the Ubiant Building.
    Legacy ``WS_*`` endpoints take form-urlencoded bodies, newer ones take JSON.
    The full OpenAPI spec is served by the instance itself at ``{base_url}/swagger.json``.
    """

    def __init__(self, base_url: str, user_id: str, session: aiohttp.ClientSession):
        self._base_url = base_url.rstrip("/")
        self._user_id = user_id
        self._session = session
        self._token: str | None = None

    @property
    def token(self) -> str | None:
        return self._token

    @property
    def base_url(self) -> str:
        return self._base_url

    def _headers(self, include_auth: bool = True, json_body: bool = False) -> dict[str, str]:
        h = {
            "X-Logged-User": self._user_id,
            "Content-Type": "application/json"
            if json_body
            else "application/x-www-form-urlencoded",
        }
        if include_auth and self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    # ------------------------------------------------------------------ auth

    async def login(self, email: str, auth_token: str, kernel_id: str) -> HemisUser:
        """Login against Hemis using building credentials.

        - email: same as Ubiant user email
        - auth_token: building.authorizationToken (used as "password" form field)
        - kernel_id: building.kernel_slot
        """
        form = {"email": email, "password": auth_token, "kernelId": kernel_id}
        try:
            async with self._session.post(
                f"{self._base_url}/WS_UserManagement/login",
                data=form,
                headers=self._headers(include_auth=False),
            ) as resp:
                if resp.status == 429:
                    raise FlexomRateLimitError("Hemis login rate-limited")
                if resp.status in (400, 401, 403):
                    body = await resp.text()
                    raise FlexomAuthError(f"Hemis login failed ({resp.status}): {body[:200]}")
                resp.raise_for_status()
                data = await resp.json()
        except aiohttp.ClientError as e:
            raise FlexomNetworkError(f"Hemis login network error: {e}") from e

        user = HemisUser.model_validate(data)
        self._token = user.token
        _log.debug("Hemis login OK (version=%s)", user.hemisVersion)
        return user

    # --------------------------------------------------------------- helpers

    async def _get_json(self, path: str, params: dict[str, str] | None = None) -> Any:
        if not self._token:
            raise FlexomAuthError("Not logged in to Hemis")
        try:
            async with self._session.get(
                f"{self._base_url}{path}",
                params=params or None,
                headers=self._headers(),
            ) as resp:
                if resp.status == 429:
                    raise FlexomRateLimitError(f"Hemis rate-limited on {path}")
                if resp.status in (401, 403):
                    raise FlexomAuthError(f"Hemis unauthorized on {path} ({resp.status})")
                resp.raise_for_status()
                return await resp.json()
        except aiohttp.ClientError as e:
            raise FlexomNetworkError(f"Hemis GET {path} network error: {e}") from e

    async def _put(
        self,
        path: str,
        *,
        form: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> None:
        if not self._token:
            raise FlexomAuthError("Not logged in to Hemis")
        try:
            async with self._session.put(
                f"{self._base_url}{path}",
                data=form,
                json=json_body,
                headers=self._headers(json_body=json_body is not None),
            ) as resp:
                if resp.status == 429:
                    raise FlexomRateLimitError(f"Hemis rate-limited on PUT {path}")
                if resp.status in (401, 403):
                    raise FlexomAuthError(f"Hemis unauthorized on PUT {path} ({resp.status})")
                if resp.status >= 400:
                    body = await resp.text()
                    raise FlexomNetworkError(
                        f"Hemis PUT {path} failed ({resp.status}): {body[:200]}"
                    )
        except aiohttp.ClientError as e:
            raise FlexomNetworkError(f"Hemis PUT {path} network error: {e}") from e

    @staticmethod
    def _filter_params(zone_id: str | None, factors: list[str] | None) -> dict[str, str]:
        params: dict[str, str] = {}
        if zone_id:
            params["zoneId"] = zone_id
        if factors:
            params["factorsFilter"] = ",".join(factors)
        return params

    # ---------------------------------------------------------------- system

    async def get_status(self) -> HemisStatus:
        return HemisStatus.model_validate(await self._get_json("/WS_SystemManagement/status"))

    async def get_infos(self) -> HemisInfos:
        return HemisInfos.model_validate(await self._get_json("/WS_SystemManagement/infos"))

    async def get_features(self) -> list[str]:
        data = await self._get_json("/WS_SystemManagement/features")
        return list(data) if isinstance(data, list) else []

    # ----------------------------------------------------------------- zones

    async def get_zones(self) -> list[Zone]:
        data = await self._get_json("/WS_ZoneManagement/list")
        assert isinstance(data, list)
        zones = [Zone.model_validate(z) for z in data]
        for z in zones:
            if z.id == MASTER_ZONE_ID:
                z.name = "Ma Maison"
        return zones

    async def get_zone_settings(self, zone_id: str) -> dict[str, Settings]:
        data = await self._get_json(
            f"/WS_ReactiveEnvironmentDataManagement/{zone_id}/settings"
        )
        assert isinstance(data, dict)
        return {k: Settings.model_validate(v) for k, v in data.items()}

    async def get_all_settings(
        self, zone_id: str | None = None, factors: list[str] | None = None
    ) -> dict[str, dict[str, Settings]]:
        """Settings of every zone in ONE call: {zoneId: {factor: Settings}}."""
        data = await self._get_json(
            "/WS_ReactiveEnvironmentDataManagement/settings",
            params=self._filter_params(zone_id, factors),
        )
        assert isinstance(data, dict)
        return {
            zid: {f: Settings.model_validate(s) for f, s in (zsettings or {}).items()}
            for zid, zsettings in data.items()
        }

    async def set_zone_factor(self, zone_id: str, factor: str, value: float) -> None:
        """Set a factor target value on a zone.

        Units per factor (learnt empirically):
          - BRI, BRIEXT: float 0.0-1.0 (API displays as %)
          - TMP: float in degrees C (range given by Settings.min/max, typically 7.0-35.0)
        """
        await self._put(
            f"/WS_ReactiveEnvironmentDataManagement/{zone_id}/settings/{factor}/value",
            form={"value": str(value)},
        )

    # ---------------------------------------------------------------- things

    async def get_things(self) -> list[Thing]:
        data = await self._get_json("/intelligent-things/listV2")
        assert isinstance(data, list)
        return [Thing.model_validate(t) for t in data]

    async def get_sensors(
        self, zone_id: str | None = None, factors: list[str] | None = None
    ) -> list[Sensor]:
        """Flat list of every sensor with its current state (one call)."""
        data = await self._get_json(
            "/intelligent-things/sensors", params=self._filter_params(zone_id, factors)
        )
        assert isinstance(data, list)
        return [Sensor.model_validate(s) for s in data]

    async def get_actuators(
        self, zone_id: str | None = None, factors: list[str] | None = None
    ) -> list[Actuator]:
        """Flat list of every actuator with target / hardware states (one call)."""
        data = await self._get_json(
            "/intelligent-things/actuators", params=self._filter_params(zone_id, factors)
        )
        assert isinstance(data, list)
        return [Actuator.model_validate(a) for a in data]

    async def set_actuator_state(
        self,
        it_id: str,
        actuator_id: str,
        value: float,
        duration_ms: int | None = None,
    ) -> None:
        """Drive ONE actuator directly (bypasses the zone factor).

        ``duration_ms`` is how long the override lasts before Hemis resumes
        automatic regulation (only meaningful when regulation is enabled).
        """
        body: dict[str, Any] = {"value": value}
        if duration_ms is not None:
            body["duration"] = duration_ms
        await self._put(
            f"/intelligent-things/{it_id}/actuator/{actuator_id}/state", json_body=body
        )
