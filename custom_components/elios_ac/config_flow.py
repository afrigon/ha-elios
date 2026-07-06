"""Config flow: a host, validated by asking the device who it is."""

from typing import Any

import broadlink6
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_MAC
from homeassistant.helpers.device_registry import format_mac

from .const import CONF_DEVTYPE, DOMAIN

USER_SCHEMA = vol.Schema({vol.Required(CONF_HOST): str})


class EliosConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            try:
                info = await self.hass.async_add_executor_job(broadlink6.hello, host)
            except broadlink6.BroadlinkError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(format_mac(info.mac.hex(":")))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Elios AC ({host})",
                    data={
                        CONF_HOST: host,
                        CONF_MAC: info.mac.hex(),
                        CONF_DEVTYPE: info.devtype,
                    },
                )

        return self.async_show_form(
            step_id="user", data_schema=USER_SCHEMA, errors=errors
        )
