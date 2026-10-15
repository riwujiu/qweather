"""Authenticated QWeather v1 transport; never place credentials in URLs."""
import asyncio
import math
import re

import aiohttp
import voluptuous as vol


class QWeatherError(Exception):
    """A sanitized upstream failure."""


def validate_host(value):
    value = str(value).strip().lower()
    if not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+qweatherapi\.com", value):
        raise vol.Invalid("api_host must be your assigned qweatherapi.com hostname, without scheme or path")
    return value


def coordinates(value):
    """Keep original longitude,latitude YAML order; v1 paths reverse it."""
    try:
        longitude, latitude = map(float, str(value).split(","))
        if not (math.isfinite(longitude) and math.isfinite(latitude)
                and -180 <= longitude <= 180 and -90 <= latitude <= 90):
            raise ValueError
    except (TypeError, ValueError) as err:
        raise vol.Invalid("location must be longitude,latitude") from err
    return round(latitude, 2), round(longitude, 2)


class QWeatherClient:
    def __init__(self, session, host, key, latitude, longitude, days=7, hours=24, extras=(), auth=None):
        self._session = session
        self._host = validate_host(host)
        self._key = key
        self._auth = auth
        self.latitude, self.longitude = latitude, longitude
        self.days, self.hours = days, hours
        self.extras = extras

    async def _get(self, endpoint, **params):
        return await self._request(f"/weather/v1/{endpoint}/{self.latitude:.2f}/{self.longitude:.2f}", **params)

    async def _request(self, path, **params):
        url = f"https://{self._host}{path}"
        try:
            async with self._session.get(
                url, headers=self._auth.headers() if self._auth else {"X-QW-Api-Key": self._key},
                params={"lang": "zh", "localTime": "true", **params},
                timeout=aiohttp.ClientTimeout(total=20), allow_redirects=False,
            ) as response:
                if response.status != 200:
                    raise QWeatherError(f"QWeather HTTP {response.status}")
                data = await response.json()
                if not isinstance(data, dict) or "error" in data or str(data.get("code", "200")) != "200":
                    raise QWeatherError("Invalid QWeather response")
                return data
        except (aiohttp.ClientError, TimeoutError, ValueError):
            raise QWeatherError("QWeather request failed") from None

    async def fetch(self):
        # Sequential requests avoid orphan tasks if a request fails.
        async with asyncio.timeout(60):
            current = await self._get("current")
            daily = await self._get("daily", days=self.days)
            hourly = await self._get("hourly", hours=self.hours)
        return current, daily, hourly

    async def fetch_extras(self):
        """Each supplemental product fails independently from core weather."""
        paths = {
            "air": f"/airquality/v1/current/{self.latitude:.2f}/{self.longitude:.2f}",
            "alerts": f"/weatheralert/v1/current/{self.latitude:.2f}/{self.longitude:.2f}",
            "minutely": "/v7/minutely/5m",
        }
        result = {}
        for name in self.extras:
            try:
                params = {"location": f"{self.longitude:.2f},{self.latitude:.2f}"} if name == "minutely" else {}
                result[name] = await self._request(paths[name], **params)
            except QWeatherError:
                result[name] = None
        return result
