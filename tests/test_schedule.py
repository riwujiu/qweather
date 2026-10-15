"""Exercise local-time boundaries and actual scheduled entity refresh gating."""
from datetime import datetime, timedelta, timezone
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from custom_components.qweather.schedule import refresh_interval
from custom_components.qweather.settings import DEFAULTS, normalize
from custom_components.qweather.api import QWeatherClient
from custom_components.qweather.weather import QWeather

TZ = ZoneInfo("Asia/Shanghai")
SETTINGS = {**DEFAULTS, "interval":600, "night_enabled":True, "night_interval":1800}


class ScheduleTests(IsolatedAsyncioTestCase):
    def test_boundaries_cross_midnight_and_disable(self):
        for hour, minute, expected in [(0,0,1800),(6,59,1800),(7,0,600),(23,59,600)]:
            self.assertEqual(refresh_interval(SETTINGS,datetime(2026,10,15,hour,minute,tzinfo=TZ)),expected)
        overnight={**SETTINGS,"night_start":22,"night_end":7}
        for hour, expected in [(21,600),(22,1800),(0,1800),(6,1800),(7,600)]:
            self.assertEqual(refresh_interval(overnight,datetime(2026,10,15,hour,tzinfo=TZ)),expected)
        for settings in [{**SETTINGS,"night_enabled":False},{**SETTINGS,"night_start":7,"night_end":7}]:
            self.assertEqual(refresh_interval(settings,datetime(2026,10,15,0,tzinfo=TZ)),600)

    async def test_due_refresh_day_night_boundary_and_failed_attempt(self):
        entity=QWeather(QWeatherClient(None,"test.re.qweatherapi.com","test",28.22,112.92),"Test",interval=600,schedule=SETTINGS)
        entity._async_refresh=AsyncMock()
        local=datetime(2026,10,15,23,50,tzinfo=TZ)
        async def advance(minutes):
            nonlocal local
            local+=timedelta(minutes=minutes)
            with patch("custom_components.qweather.weather.dt_util.now",return_value=local),patch("custom_components.qweather.weather.dt_util.utcnow",return_value=local.astimezone(timezone.utc)):
                return await entity.async_update(scheduled=True)
        self.assertTrue(await advance(0))
        self.assertFalse(await advance(9))
        self.assertFalse(await advance(1))  # Midnight switches to the 30-minute interval.
        self.assertTrue(await advance(20))
        self.assertEqual(entity._async_refresh.await_count,2)
        # At 07:00 the shorter interval applies immediately, even if night was not due.
        local=datetime(2026,10,16,6,45,tzinfo=TZ)
        entity._last_refresh_at=local.astimezone(timezone.utc)
        self.assertFalse(await advance(14))
        self.assertTrue(await advance(1))
        self.assertFalse(await advance(9))
        self.assertTrue(await advance(1))
        # Even an unexpected error must not turn the local one-minute check into retries.
        entity._async_refresh.side_effect=RuntimeError("test failure")
        with self.assertRaises(RuntimeError): await advance(10)
        self.assertFalse(await advance(1))

    def test_legacy_and_invalid_settings(self):
        base={"api_host":"test.re.qweatherapi.com","api_key":"test","location":"112.92,28.22","interval":900}
        result=normalize(base)
        self.assertFalse(result["night_enabled"])
        self.assertEqual(result["interval"],900)
        for field,value in [("night_start",24),("night_end",-1),("night_interval",299),("night_enabled","false")]:
            with self.assertRaises(ValueError): normalize({**base,field:value})
