"""Config flow for Flexom 2.0."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD

from .const import DOMAIN
from .flexom_client import FlexomClient
from .flexom_client.errors import FlexomAuthError, FlexomError

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def _validate_credentials(email: str, password: str) -> str:
    """Try to log in and return the building id on success."""
    client = FlexomClient(email=email, password=password)
    await client.__aenter__()
    try:
        assert client.building is not None
        return client.building.buildingId
    finally:
        await client.__aexit__(None, None, None)


class FlexomConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Flexom 2.0."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL]
            password = user_input[CONF_PASSWORD]
            try:
                building_id = await _validate_credentials(email, password)
            except FlexomAuthError:
                errors["base"] = "invalid_auth"
            except FlexomError as e:
                _LOGGER.error("Flexom connection error: %s", e)
                errors["base"] = "cannot_connect"
            except Exception as e:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during Flexom setup: %s", e)
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(building_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Flexom ({email})",
                    data={CONF_EMAIL: email, CONF_PASSWORD: password},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
