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
from homeassistant.helpers import entity_registry

from custom_components.qweather.api import QWeatherClient


async def main():
    root = Path(tempfile.mkdtemp(prefix="qweather-smoke-"))
    source = Path(__file__).resolve().parents[1]
    shutil.copytree(source / "custom_components", root / "custom_components")
    live = "--live" in sys.argv
    credentials = json.load(sys.stdin) if live else {"api_host": "example.re.qweatherapi.com", "api_key": "test"}
    config = {"homeassistant": {"name": "QWeather smoke", "time_zone": "Asia/Shanghai", "unit_system": "metric"},
              "weather": [{"platform": "qweather", "name": "QWeather Test", "location": "112.92,28.22", "extras": ["air", "alerts", "minutely"], **credentials}]}
    jwt_data = config["weather"][0].copy() if credentials.get("auth_type") == "jwt" else None
    if jwt_data:
        config["weather"] = []
        jwt_data.pop("platform")
    payloads = [json.loads((source / "tests" / "fixtures" / f"{name}.json").read_text(encoding="utf-8-sig")) for name in ("current", "daily", "hourly")]
    async def fake_fetch(self):
        return tuple(payloads)
    async def fake_extras(self):
        return {name: json.loads((source / "tests" / "fixtures" / f"{name}.json").read_text(encoding="utf-8-sig")) for name in ("air", "alerts", "minutely")}
    original = QWeatherClient.fetch
    original_extras = QWeatherClient.fetch_extras
    hass = HomeAssistant(str(root))
    loader.async_setup(hass)
    try:
        with patch.object(QWeatherClient, "fetch", original if live else fake_fetch), patch.object(QWeatherClient, "fetch_extras", original_extras if live else fake_extras):
            result = await bootstrap.async_from_config_dict(config, hass)
            if jwt_data:
                flow = await hass.config_entries.flow.async_init("qweather", context={"source": "user"}, data=jwt_data)
                assert flow["type"] == "create_entry", "JWT flow failed"
            await hass.async_block_till_done()
            await hass.async_start()
            await hass.async_block_till_done()
            states = hass.states.async_all("weather")
            assert result and len(states) == 1, "Weather entity not created"
            state = states[0]
            entries = hass.config_entries.async_entries("qweather")
            assert len(entries) == 1 and entries[0].state.value == "loaded", "Config entry not loaded"
            registered = entity_registry.async_get(hass).async_get(state.entity_id)
            assert registered.config_entry_id == entries[0].entry_id, "Entity not attached to UI entry"
            assert state.state not in ("unknown", "unavailable"), "Weather unavailable"
            assert state.attributes.get("air_available") and state.attributes.get("alerts_available") and state.attributes.get("minutely_available"), "Supplemental product unavailable"
            assert state.attributes.get("pm25") is not None
            assert state.attributes.get("precipitation_next_24h") is not None
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
