"""UI setup, YAML import, options and credential reconfiguration."""
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import selector

from .api import QWeatherClient, QWeatherError, coordinates
from .const import DOMAIN
from .data import current_attributes, daily_forecasts, hourly_forecasts
from .settings import DEFAULTS, OPTIONS, normalize, location_id
from .auth import async_auth


def form_schema(defaults, credentials=False, new=False):
    fields = {}
    fields[vol.Required("name", default=defaults.get("name", DEFAULTS["name"]))] = str
    if credentials:
        fields[vol.Required("api_host", default=defaults.get("api_host", ""))] = str
        # Existing keys are never put into the form response. Blank preserves it.
        fields[vol.Required("auth_type", default=defaults.get("auth_type", "api_key"))] = selector.SelectSelector(
            selector.SelectSelectorConfig(options=["api_key", "jwt"], translation_key="auth_type")
        )
        key_field = vol.Optional("api_key", default="")
        fields[key_field] = selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))
        for field in ("key_id", "developer_id", "project_id", "private_key_file"):
            fields[vol.Optional(field, default=defaults.get(field, "/config/.qweather-jwt/ed25519-private.pem" if field == "private_key_file" else ""))] = str
        fields[vol.Required("location", default=defaults.get("location", ""))] = str
    fields[vol.Required("night_enabled", default=defaults.get("night_enabled", DEFAULTS["night_enabled"]))] = bool
    for key, low, high in (("default", 1, 10), ("hours", 1, 240), ("interval", 300, 86400),
                           ("night_interval", 300, 86400), ("night_start", 0, 23), ("night_end", 0, 23)):
        fields[vol.Required(key, default=defaults.get(key, DEFAULTS[key]))] = vol.All(vol.Coerce(int), vol.Range(min=low, max=high))
    fields[vol.Required("extras", default=defaults.get("extras", []))] = selector.SelectSelector(
        selector.SelectSelectorConfig(options=["air", "alerts", "minutely"], multiple=True, translation_key="extras")
    )
    return vol.Schema(fields)


async def validate_connection(hass, data):
    latitude, longitude = coordinates(data["location"])
    auth = await async_auth(hass, data)
    client = QWeatherClient(async_get_clientsession(hass), data["api_host"], data.get("api_key"), latitude, longitude, data["default"], data["hours"], auth=auth)
    current, daily, hourly = await client.fetch()
    current_attributes(current)
    daily_forecasts(daily)
    hourly_forecasts(hourly)


class QWeatherConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return QWeatherOptionsFlow()

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                data = normalize(user_input)
                await self.async_set_unique_id(location_id(data))
                self._abort_if_unique_id_configured()
                await validate_connection(self.hass, data)
            except (vol.Invalid, ValueError, TypeError, KeyError, AttributeError):
                errors["base"] = "invalid_settings"
            except (QWeatherError, TimeoutError):
                errors["base"] = "cannot_connect"
            else:
                data["entity_unique_id"] = location_id(data)
                return self.async_create_entry(title=data["name"], data=data)
        defaults = {**DEFAULTS, "location": f"{self.hass.config.longitude:.2f},{self.hass.config.latitude:.2f}", **(user_input or {})}
        return self.async_show_form(step_id="user", data_schema=form_schema(defaults, credentials=True, new=True), errors=errors)

    async def async_step_import(self, user_input):
        # Import must also work during an upstream outage. Entity polling handles it.
        try:
            data = normalize(user_input)
        except (vol.Invalid, ValueError, TypeError, KeyError):
            return self.async_abort(reason="invalid_settings")
        await self.async_set_unique_id(location_id(data))
        self._abort_if_unique_id_configured()
        data["entity_unique_id"] = location_id(data)
        return self.async_create_entry(title=data["name"], data=data)

    async def async_step_reconfigure(self, user_input=None):
        entry = self._get_reconfigure_entry()
        current = {**entry.data, **entry.options}
        errors = {}
        if user_input is not None:
            candidate = {**current, **user_input}
            candidate["api_key"] = user_input.get("api_key") or current.get("api_key", "")
            try:
                data = normalize(candidate)
                uid = location_id(data)
                if any(e.entry_id != entry.entry_id and e.unique_id == uid for e in self._async_current_entries()):
                    return self.async_abort(reason="already_configured")
                await validate_connection(self.hass, data)
            except (vol.Invalid, ValueError, TypeError, KeyError, AttributeError):
                errors["base"] = "invalid_settings"
            except (QWeatherError, TimeoutError):
                errors["base"] = "cannot_connect"
            else:
                # Keep the original weather entity identity even after a location edit.
                data["entity_unique_id"] = entry.data.get("entity_unique_id", entry.unique_id)
                return self.async_update_reload_and_abort(entry, unique_id=uid, title=data["name"], data=data, options={})
        defaults = {**current, **(user_input or {})}
        return self.async_show_form(step_id="reconfigure", data_schema=form_schema(defaults, credentials=True), errors=errors)


class QWeatherOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        current = {**self.config_entry.data, **self.config_entry.options}
        errors = {}
        if user_input is not None:
            try:
                data = normalize({**current, **user_input})
            except (vol.Invalid, ValueError, TypeError, KeyError):
                errors["base"] = "invalid_settings"
            else:
                return self.async_create_entry(title="", data={k: data[k] for k in OPTIONS})
        return self.async_show_form(step_id="init", data_schema=form_schema({**current, **(user_input or {})}), errors=errors)
