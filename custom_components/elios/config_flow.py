"""Config flow: pick the remote entity that faces the AC, and optional sensors."""

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.selector import EntitySelector, EntitySelectorConfig

from .const import (
    CONF_HUMIDITY_SENSOR,
    CONF_REMOTE_ENTITY,
    CONF_TEMPERATURE_SENSOR,
    DOMAIN,
)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_REMOTE_ENTITY): EntitySelector(
            EntitySelectorConfig(domain="remote")
        ),
        vol.Optional(CONF_TEMPERATURE_SENSOR): EntitySelector(
            EntitySelectorConfig(domain="sensor", device_class="temperature")
        ),
        vol.Optional(CONF_HUMIDITY_SENSOR): EntitySelector(
            EntitySelectorConfig(domain="sensor", device_class="humidity")
        ),
    }
)


class EliosConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="Elios AC", data=user_input)

        return self.async_show_form(step_id="user", data_schema=USER_SCHEMA)
