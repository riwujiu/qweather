"""Run with unittest in a Home Assistant Python environment."""
import json
from pathlib import Path
import unittest
from unittest.mock import AsyncMock

import homeassistant  # Install HA's schema compatibility layer before voluptuous.
import voluptuous as vol

from custom_components.qweather.api import QWeatherClient, QWeatherError, coordinates, validate_host
from custom_components.qweather.condition import CONDITION_MAP
from custom_components.qweather.data import current_attributes, daily_forecasts, hourly_forecasts
from custom_components.qweather.weather import QWeather, PLATFORM_SCHEMA

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8-sig"))


class DataTests(unittest.TestCase):
    def test_coordinates_and_host(self):
        self.assertEqual(coordinates("112.943,28.234"), (28.23, 112.94))
        self.assertEqual(validate_host("ABC.re.qweatherapi.com"), "abc.re.qweatherapi.com")
        for bad in ["devapi.qweather.com", "https://abc.qweatherapi.com", "abc.qweatherapi.com.evil.org", "user@abc.qweatherapi.com"]:
            with self.assertRaises(vol.Invalid):
                validate_host(bad)
        for bad in ["nan,28", "181,28", "112,91", "112", "112,28,4"]:
            with self.assertRaises(vol.Invalid):
                coordinates(bad)

    def test_current_units_and_fractions(self):
        data = fixture("current")
        attrs = current_attributes(data)
        self.assertEqual(attrs["native_temperature"], data["temperature"]["value"])
        self.assertEqual(attrs["humidity"], round(data["humidity"] * 100))
        self.assertEqual(attrs["native_wind_speed"], data["wind"]["speed"]["value"])
        self.assertEqual(attrs["native_visibility"], data["visibility"]["value"])
        self.assertTrue(attrs["extra_state_attributes"]["attributions"])

    def test_missing_optional_and_bad_units(self):
        data = {"condition": {"code": "100"}, "temperature": {"value": 20, "unit": "°C"}}
        self.assertIsNone(current_attributes(data)["humidity"])
        data["temperature"]["unit"] = "°F"
        with self.assertRaises(ValueError):
            current_attributes(data)

    def test_daily_full_day_extrema_and_rain(self):
        payload = fixture("daily")
        rows = daily_forecasts(payload)
        self.assertEqual(len(rows), 7)
        for original, row in zip(payload["days"], rows):
            self.assertEqual(row["native_temperature"], original["temperatureMax"]["value"])
            self.assertEqual(row["native_templow"], original["temperatureMin"]["value"])
            self.assertNotIn("precipitation_probability", row)
            rain = sum(original[part]["precipitation"]["amount"]["value"] for part in ("daytime", "nighttime"))
            self.assertAlmostEqual(row["native_precipitation"], rain, places=3)
            self.assertEqual(row["datetime"][:10], original["forecastStartTime"][:10])

    def test_hourly_timestamps_and_real_probability(self):
        payload = fixture("hourly")
        rows = hourly_forecasts(payload)
        self.assertEqual(len(rows), 24)
        self.assertEqual(rows[0]["precipitation_probability"], round(payload["hours"][0]["precipitation"]["probability"] * 100))
        self.assertIn("+08:00", rows[0]["datetime"])

    def test_invalid_data(self):
        for data in [{}, {"temperature": {"value": float("nan"), "unit": "°C"}}]:
            with self.assertRaises(ValueError):
                current_attributes(data)
        with self.assertRaises(ValueError):
            daily_forecasts({"days": []})
        data = fixture("hourly")
        data["hours"][0]["forecastTime"] = "2026-10-15T01:00"
        with self.assertRaises(ValueError):
            hourly_forecasts(data)

    def test_all_conditions_are_valid_ha_states(self):
        allowed = {"clear-night", "cloudy", "exceptional", "fog", "hail", "lightning", "lightning-rainy", "partlycloudy", "pouring", "rainy", "snowy", "snowy-rainy", "sunny", "windy", "windy-variant"}
        self.assertTrue(set(CONDITION_MAP.values()) <= allowed)
        self.assertEqual(CONDITION_MAP["407"], "snowy")

    def test_yaml_schema(self):
        cfg = PLATFORM_SCHEMA({"platform": "qweather", "api_host": "example.re.qweatherapi.com", "api_key": "test", "location": "112.94,28.23"})
        self.assertEqual(cfg["location"], (28.23, 112.94))
        self.assertEqual(cfg["default"], 7)


class AsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_transport_auth_path_and_status(self):
        class Response:
            status = 200
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def json(self): return fixture("current")
        class Session:
            def get(self, url, **kwargs):
                self.url, self.kwargs = url, kwargs
                return response
        response, session = Response(), Session()
        client = QWeatherClient(session, "example.re.qweatherapi.com", "fake-secret", 28.23, 112.94)
        await client._get("current")
        self.assertTrue(session.url.endswith("/weather/v1/current/28.23/112.94"))
        self.assertNotIn("fake-secret", session.url)
        self.assertEqual(session.kwargs["headers"], {"X-QW-Api-Key": "fake-secret"})
        self.assertFalse(session.kwargs["allow_redirects"])
        for status in (301, 401, 403, 429, 500):
            response.status = status
            with self.assertRaises(QWeatherError):
                await client._get("current")

    async def test_refresh_failure_clears_forecasts_then_recovers(self):
        client = QWeatherClient(None, "example.re.qweatherapi.com", "test", 28.23, 112.94)
        payload = tuple(fixture(name) for name in ("current", "daily", "hourly"))
        client.fetch = AsyncMock(return_value=payload)
        entity = QWeather(client, "Test")
        await entity.async_update()
        self.assertTrue(entity.available)
        self.assertEqual(len(await entity.async_forecast_daily()), 7)
        client.fetch.side_effect = QWeatherError("HTTP 401")
        await entity.async_update()
        self.assertFalse(entity.available)
        self.assertIsNone(await entity.async_forecast_daily())
        self.assertIsNone(await entity.async_forecast_hourly())
        client.fetch.side_effect = None
        await entity.async_update()
        self.assertTrue(entity.available)

    async def test_partial_payload_does_not_publish_mixed_data(self):
        client = QWeatherClient(None, "example.re.qweatherapi.com", "test", 28.23, 112.94)
        client.fetch = AsyncMock(return_value=(fixture("current"), {"days": []}, fixture("hourly")))
        entity = QWeather(client, "Test")
        await entity.async_update()
        self.assertFalse(entity.available)


if __name__ == "__main__":
    unittest.main()
