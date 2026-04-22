from __future__ import annotations

import logging

import aiohttp

from .errors import FlexomAuthError, FlexomNetworkError, FlexomRateLimitError
from .models import MASTER_ZONE_ID, HemisUser, Settings, Thing, Zone

_log = logging.getLogger(__name__)


class HemisService:
    """REST client for the per-building Hemis layer.

    Content-Type is application/x-www-form-urlencoded (NOT JSON).
    All requests must carry the X-Logged-User header with the Ubiant user id.
    """

    def __init__(self, base_url: str, user_id: str, session: aiohttp.ClientSession):
        self._base_url = base_url.rstrip("/")
        self._user_id = user_id
        self._session = session
        self._token: str | None = None

    @property
    def token(self) -> str | None:
        return self._token

    def _headers(self, include_auth: bool = True) -> dict[str, str]:
        h = {
            "X-Logged-User": self._user_id,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        if include_auth and self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

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
        _log.debug("Hemis login OK")
        return user

    async def _get_json(self, path: str) -> object:
        if not self._token:
            raise FlexomAuthError("Not logged in to Hemis")
        try:
            async with self._session.get(
                f"{self._base_url}{path}",
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

    async def get_things(self) -> list[Thing]:
        data = await self._get_json("/intelligent-things/listV2")
        assert isinstance(data, list)
        return [Thing.model_validate(t) for t in data]

    async def set_zone_factor(self, zone_id: str, factor: str, value: float) -> None:
        """Set a factor's target value on a zone.

        Units per factor (learnt empirically):
          - BRI, BRIEXT: float 0.0-1.0 (API displays as %)
          - TMP: float in °C (range provided by Settings.min/max, typically 7.0-35.0)
        """
        if not self._token:
            raise FlexomAuthError("Not logged in to Hemis")
        url = (
            f"{self._base_url}/WS_ReactiveEnvironmentDataManagement/"
            f"{zone_id}/settings/{factor}/value"
        )
        try:
            async with self._session.put(
                url,
                data={"value": str(value)},
                headers=self._headers(),
            ) as resp:
                if resp.status == 429:
                    raise FlexomRateLimitError(f"Hemis rate-limited on PUT {url}")
                if resp.status in (401, 403):
                    raise FlexomAuthError(
                        f"Hemis unauthorized on PUT {url} ({resp.status})"
                    )
                resp.raise_for_status()
        except aiohttp.ClientError as e:
            raise FlexomNetworkError(f"Hemis PUT {url} network error: {e}") from e
        _log.info("set_zone_factor %s/%s = %s", zone_id, factor, value)
