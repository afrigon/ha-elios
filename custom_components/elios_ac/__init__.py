"""Elios air conditioner via a Broadlink RM4 reached over IPv6."""

import broadlink6

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_MAC, Platform
from homeassistant.core import HomeAssistant

from .const import CONF_DEVTYPE

PLATFORMS = [Platform.CLIMATE]

type EliosConfigEntry = ConfigEntry[broadlink6.Device]


async def async_setup_entry(hass: HomeAssistant, entry: EliosConfigEntry) -> bool:
    entry.runtime_data = broadlink6.Device(
        entry.data[CONF_HOST],
        entry.data[CONF_DEVTYPE],
        entry.data[CONF_MAC],
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EliosConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
