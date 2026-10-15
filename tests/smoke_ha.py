"""Disposable HA lifecycle + forecast service test. --live reads JSON from stdin."""
import asyncio
import json
from pathlib import Path
import shutil
import sys
import tempfile
from unittest.mock import patch

from homeassistant import bootstrap, loader
from homeassistant.core import HomeAssistant

from custom_components.qweather.api import QWeatherClient


async def main():
    root = Path(tempfile.mkdtemp(prefix="qweather-smoke-"))
    source = Path(__file__).resolve().parents[1]
    shutil.copytree(source / "custom_components", root / "custom_components")
    live = "--live" in sys.argv
    credentials = json.load(sys.stdin) if live else {"api_host": "example.re.qweatherapi.com", "api_key": "test"}
    config = {"homeassistant": {"name": "QWeather smoke", "time_zone": "Asia/Shanghai", "unit_system": "metric"},
              "weather": [{"platform": "qweather", "name": "QWeather Test", "location": "112.94,28.23", **credentials}]}
    payloads = [json.loads((source / "tests" / "fixtures" / f"{name}.json").read_text(encoding="utf-8-sig")) for name in ("current", "daily", "hourly")]
    async def fake_fetch(self):
        return tuple(payloads)
    original = QWeatherClient.fetch
    hass = HomeAssistant(str(root))
    loader.async_setup(hass)
    try:
        with patch.object(QWeatherClient, "fetch", original if live else fake_fetch):
            result = await bootstrap.async_from_config_dict(config, hass)
            await hass.async_block_till_done()
            await hass.async_start()
            await hass.async_block_till_done()
            states = hass.states.async_all("weather")
            assert result and len(states) == 1, "Weather entity not created"
            state = states[0]
            assert state.state not in ("unknown", "unavailable"), "Weather unavailable"
            for kind, count in (("daily", 7), ("hourly", 24)):
                response = await hass.services.async_call("weather", "get_forecasts", {"entity_id": state.entity_id, "type": kind}, blocking=True, return_response=True)
                rows = response[state.entity_id]["forecast"]
                assert len(rows) == count, f"Wrong {kind} count"
                assert "temperature" in rows[0] and "datetime" in rows[0]
                if kind == "daily":
                    assert "templow" in rows[0]
                print(f"{kind} service OK: {len(rows)} rows", flush=True)
            print(json.dumps({"mode": "live" if live else "fixture", "state": state.state, "temperature": state.attributes["temperature"], "wind_speed_unit": state.attributes["wind_speed_unit"], "visibility_unit": state.attributes["visibility_unit"]}), flush=True)
    finally:
        await hass.async_stop()
        shutil.rmtree(root)


if __name__ == "__main__":
    asyncio.run(main())
