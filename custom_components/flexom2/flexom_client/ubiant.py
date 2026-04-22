from __future__ import annotations

import logging
import time

import aiohttp
import jwt

from .errors import FlexomAuthError, FlexomNetworkError, FlexomRateLimitError
from .models import Building, UbiantUser

UBIANT_BASE_URL = "https://hemisphere.ubiant.com"

_log = logging.getLogger(__name__)


class UbiantService:
    """REST client for the Ubiant user/building layer.

    Two endpoints only:
      - POST /users/signin (JSON) → UbiantUser (with JWT)
      - GET  /buildings/mine/infos (Bearer) → list[Building]
    """

    def __init__(self, session: aiohttp.ClientSession):
        self._session = session
        self._token: str | None = None

    @property
    def token(self) -> str | None:
        return self._token

    def is_token_valid(self, margin_seconds: int = 20 * 60) -> bool:
        if not self._token:
            return False
        try:
            claims = jwt.decode(self._token, options={"verify_signature": False})
        except jwt.PyJWTError:
            return False
        exp = claims.get("exp")
        if not isinstance(exp, (int, float)):
            return False
        return (exp - time.time()) > margin_seconds

    async def login(self, email: str, password: str) -> UbiantUser:
        try:
            async with self._session.post(
                f"{UBIANT_BASE_URL}/users/signin",
                json={"email": email, "password": password},
                headers={"Content-Type": "application/json"},
            ) as resp:
                if resp.status == 429:
                    raise FlexomRateLimitError("Ubiant login rate-limited (HTTP 429)")
                if resp.status in (400, 401, 403):
                    body = await resp.text()
                    raise FlexomAuthError(f"Ubiant login failed ({resp.status}): {body[:200]}")
                resp.raise_for_status()
                data = await resp.json()
        except aiohttp.ClientError as e:
            raise FlexomNetworkError(f"Ubiant login network error: {e}") from e

        user = UbiantUser.model_validate(data)
        self._token = user.token
        _log.debug("Ubiant login OK (user=%s)", user.id)
        return user

    async def get_buildings(self) -> list[Building]:
        if not self._token:
            raise FlexomAuthError("Not logged in to Ubiant")
        try:
            async with self._session.get(
                f"{UBIANT_BASE_URL}/buildings/mine/infos",
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json",
                },
            ) as resp:
                if resp.status == 429:
                    raise FlexomRateLimitError("Ubiant get_buildings rate-limited")
                if resp.status in (401, 403):
                    raise FlexomAuthError(f"Ubiant get_buildings unauthorized ({resp.status})")
                resp.raise_for_status()
                data = await resp.json()
        except aiohttp.ClientError as e:
            raise FlexomNetworkError(f"Ubiant get_buildings network error: {e}") from e

        return [Building.model_validate(b) for b in data]
