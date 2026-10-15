"""Set up QWeather using Home Assistant configuration entries."""
from homeassistant.const import Platform

PLATFORMS = [Platform.WEATHER]


async def async_setup(hass, config):
    return True


async def async_setup_entry(hass, entry):
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass, entry):
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)
