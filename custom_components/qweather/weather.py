"""QWeather weather/v1 platform for modern Home Assistant."""
from datetime import timedelta
import asyncio
import logging

import aiohttp
import voluptuous as vol

from homeassistant.components.weather import PLATFORM_SCHEMA, WeatherEntity, WeatherEntityFeature
from homeassistant.const import UnitOfLength, UnitOfPressure, UnitOfSpeed, UnitOfTemperature
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.util import dt as dt_util

from .api import QWeatherClient, QWeatherError, coordinates, validate_host
from .data import current_attributes, daily_forecasts, hourly_forecasts, extra_attributes
from .settings import normalize
from .auth import async_auth
from .schedule import refresh_interval
from homeassistant.exceptions import ConfigEntryNotReady

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(minutes=30)
PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required("api_host"): validate_host,
    vol.Required("api_key"): cv.string,
    vol.Required("location"): coordinates,
    vol.Optional("name", default="和风天气"): cv.string,
    vol.Optional("default", default=7): vol.All(vol.Coerce(int), vol.Range(min=1, max=10)),
    vol.Optional("hours", default=24): vol.All(vol.Coerce(int), vol.Range(min=1, max=240)),
    vol.Optional("extras", default=[]): vol.All(cv.ensure_list, [vol.In(("air", "alerts", "minutely"))]),
})


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Import legacy YAML once; subsequent edits belong in the UI."""
    latitude, longitude = config["location"]
    data = {k: config[k] for k in ("name", "api_host", "api_key", "default", "hours", "extras")}
    data["location"] = f"{longitude:.2f},{latitude:.2f}"
    data["interval"] = int(config.get("scan_interval", SCAN_INTERVAL).total_seconds())
    hass.async_create_task(hass.config_entries.flow.async_init("qweather", context={"source": "import"}, data=data))


async def async_setup_entry(hass, entry, async_add_entities):
    data = normalize({**entry.data, **entry.options})
    try:
        auth = await async_auth(hass, data)
    except ValueError as err:
        raise ConfigEntryNotReady("Unable to load JWT signing key; check key file and permissions") from err
    latitude, longitude = coordinates(data["location"])
    client = QWeatherClient(async_get_clientsession(hass), data["api_host"], data.get("api_key"), latitude, longitude,
                            data["default"], data["hours"], data["extras"], auth=auth)
    entity = QWeather(client, data["name"], interval=data["interval"], schedule=data)
    entity._attr_unique_id = entry.data["entity_unique_id"]
    entity._attr_device_info = DeviceInfo(identifiers={("qweather", entry.entry_id)}, name=data["name"], manufacturer="QWeather", model="Weather API v1")
    async_add_entities([entity], True)


class QWeather(WeatherEntity):
    """Current conditions plus HA daily/hourly forecast services."""
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_pressure_unit = UnitOfPressure.HPA
    _attr_native_wind_speed_unit = UnitOfSpeed.METERS_PER_SECOND
    _attr_native_visibility_unit = UnitOfLength.METERS
    _attr_native_precipitation_unit = UnitOfLength.MILLIMETERS
    _attr_supported_features = WeatherEntityFeature.FORECAST_DAILY | WeatherEntityFeature.FORECAST_HOURLY
    _attr_attribution = "Weather data by QWeather / 和风天气"

    def __init__(self, client, name, interval=None, schedule=None):
        super().__init__()
        self._client = client
        self._attr_name = name
        self._attr_unique_id = f"qweather_v1_{client.latitude}_{client.longitude}"
        self._attr_available = False
        self._daily = []
        self._hourly = []
        self._interval = interval
        self._schedule = schedule
        self._last_refresh_at = None
        self._attr_should_poll = interval is None
        self._refresh_lock = asyncio.Lock()

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        if self._interval is not None:
            async def refresh(now):
                if await self.async_update(scheduled=True):
                    self.async_write_ha_state()
            # Check locally once per minute; only a due refresh calls the API.
            self.async_on_remove(async_track_time_interval(self.hass, refresh, timedelta(minutes=1), name="qweather refresh"))

    async def async_update(self, *, scheduled=False):
        async with self._refresh_lock:
            if scheduled:
                interval = refresh_interval(self._schedule, dt_util.now()) if self._schedule else self._interval
                if self._last_refresh_at is not None and (dt_util.utcnow() - self._last_refresh_at).total_seconds() < interval:
                    return False
            try:
                await self._async_refresh()
            finally:
                # Failed attempts also wait for the configured interval.
                self._last_refresh_at = dt_util.utcnow()
            return True

    async def _async_refresh(self):
        """Publish a complete refresh, never a mixture of old and new data."""
        try:
            current, daily, hourly = await self._client.fetch()
            attributes = current_attributes(current)
            daily_data = daily_forecasts(daily)
            hourly_data = hourly_forecasts(hourly)
            rain = [row.get("native_precipitation") for row in hourly_data[:24]]
            attributes["extra_state_attributes"]["precipitation_next_24h"] = (
                round(sum(rain), 3) if len(rain) == 24 and all(v is not None for v in rain) else None
            )
            attributes["extra_state_attributes"].update(extra_attributes(await self._client.fetch_extras()))
        except (QWeatherError, ValueError, TypeError, KeyError, AttributeError, aiohttp.ClientError, TimeoutError):
            self._attr_available = False
            self._daily = []
            self._hourly = []
            _LOGGER.warning("QWeather refresh failed; check API Host, credentials, quota and connectivity")
            if getattr(self, "hass", None) is not None:
                await self.async_update_listeners(("daily", "hourly"))
            return
        for key, value in attributes.items():
            setattr(self, f"_attr_{key}", value)
        self._daily, self._hourly = daily_data, hourly_data
        self._attr_available = True
        if getattr(self, "hass", None) is not None:
            await self.async_update_listeners(("daily", "hourly"))

    async def async_forecast_daily(self):
        if not self.available:
            return None
        return self._daily

    async def async_forecast_hourly(self):
        if not self.available:
            return None
        return self._hourly
