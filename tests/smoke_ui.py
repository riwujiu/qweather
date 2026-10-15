"""Exercise real HA config flows, entity adoption, options and lifecycle."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import tempfile
from unittest.mock import AsyncMock, patch

from homeassistant import bootstrap, loader
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.qweather.api import QWeatherClient, QWeatherError


async def main():
    source = Path(__file__).resolve().parents[1]
    root = Path(tempfile.mkdtemp(prefix="qweather-ui-smoke-"))
    shutil.copytree(source / "custom_components", root / "custom_components")
    def fixture(name):
        return json.loads((source / "tests" / "fixtures" / f"{name}.json").read_text(encoding="utf-8-sig"))
    async def fetch(self):
        return tuple(fixture(name) for name in ("current", "daily", "hourly"))
    async def extras(self):
        return {name: fixture(name) for name in ("air", "alerts", "minutely")}
    timers = []
    def track(hass, action, interval, **kwargs):
        timer = {"active": True, "action": action, "interval": interval.total_seconds()}
        timers.append(timer)
        def cancel():
            timer["active"] = False
        return cancel
    def active():
        return [t for t in timers if t["active"]]

    hass = HomeAssistant(str(root))
    loader.async_setup(hass)
    data = {"name": "Zhangsha", "api_host": "test.re.qweatherapi.com", "api_key": "private-test-key", "location": "112.92,28.22", "default": 7, "hours": 24, "interval": 600, "extras": ["air", "alerts", "minutely"]}
    try:
        with patch.object(QWeatherClient, "fetch", fetch), patch.object(QWeatherClient, "fetch_extras", extras), patch("custom_components.qweather.config_flow.validate_connection", new_callable=AsyncMock) as validate, patch("custom_components.qweather.weather.async_track_time_interval", track):
            assert await bootstrap.async_from_config_dict({"homeassistant": {"time_zone": "Asia/Shanghai"}, "weather": []}, hass)
            await hass.async_start()
            await hass.async_block_till_done()
            registry = er.async_get(hass)
            legacy = registry.async_get_or_create("weather", "qweather", "qweather_v1_28.22_112.92", suggested_object_id="zhangsha")
            first = await hass.config_entries.flow.async_init("qweather", context={"source": "user"})
            assert first["type"] == "form" and first["step_id"] == "user"
            invalid = await hass.config_entries.flow.async_configure(first["flow_id"], {**data, "api_host": "evil.example"})
            assert invalid["errors"]["base"] == "invalid_settings"
            validate.side_effect = QWeatherError("HTTP 401")
            invalid = await hass.config_entries.flow.async_configure(first["flow_id"], data)
            assert invalid["errors"]["base"] == "cannot_connect"
            validate.side_effect = None
            created = await hass.config_entries.flow.async_configure(first["flow_id"], data)
            assert created["type"] == "create_entry"
            entry = created["result"]
            await hass.async_block_till_done()
            assert entry.state.value == "loaded"
            assert len(hass.states.async_all("weather")) == 1
            assert registry.async_get("weather.zhangsha").id == legacy.id
            assert registry.async_get("weather.zhangsha").config_entry_id == entry.entry_id
            assert hass.states.get("weather.zhangsha").state not in ("unknown", "unavailable")
            assert len(active()) == 1 and active()[0]["interval"] == 60
            print("UI setup, validation, credential failure, legacy entity adoption OK", flush=True)

            duplicate = await hass.config_entries.flow.async_init("qweather", context={"source": "user"}, data=data)
            assert duplicate["type"] == "abort" and duplicate["reason"] == "already_configured"
            imported = await hass.config_entries.flow.async_init("qweather", context={"source": "import"}, data={**data, "interval": 1200})
            assert imported["type"] == "abort" and entry.data["interval"] == 600
            options = await hass.config_entries.options.async_init(entry.entry_id)
            assert options["type"] == "form"
            options = await hass.config_entries.options.async_configure(options["flow_id"], {"name": "Changsha", "default": 3, "hours": 24, "interval": 900, "night_enabled": True, "night_start": 22, "night_end": 7, "night_interval": 1800, "extras": ["alerts"]})
            assert options["type"] == "create_entry"
            await hass.async_block_till_done()
            assert entry.options["interval"] == 900
            assert entry.options["night_enabled"] and entry.options["night_start"] == 22 and entry.options["night_interval"] == 1800
            assert len(active()) == 1 and active()[0]["interval"] == 60
            assert registry.async_get("weather.zhangsha").id == legacy.id
            await active()[0]["action"](datetime.now(timezone.utc))
            print("Duplicate/import guards, options reload and single periodic refresh OK", flush=True)

            from zoneinfo import ZoneInfo
            from datetime import timedelta
            entity = hass.data["weather"].get_entity("weather.zhangsha")
            local = datetime(2026, 10, 15, 21, 50, tzinfo=ZoneInfo("Asia/Shanghai"))
            entity._last_refresh_at = local.astimezone(timezone.utc)
            with patch.object(entity, "_async_refresh", wraps=entity._async_refresh) as refresh:
                async def tick(at):
                    with patch("custom_components.qweather.weather.dt_util.now", return_value=at), patch("custom_components.qweather.weather.dt_util.utcnow", return_value=at.astimezone(timezone.utc)):
                        await active()[0]["action"](at.astimezone(timezone.utc))
                await tick(local + timedelta(minutes=10))
                assert refresh.await_count == 0  # 22:00 now uses the night interval.
                await tick(local + timedelta(minutes=30))
                assert refresh.await_count == 1
                await tick(local + timedelta(minutes=31))
                assert refresh.await_count == 1
            print("Real HA timer callback switches schedule without extra one-minute API calls OK", flush=True)

            flow = await hass.config_entries.flow.async_init("qweather", context={"source": "reconfigure", "entry_id": entry.entry_id})
            assert flow["type"] == "form" and "private-test-key" not in repr(flow["data_schema"])
            result = await hass.config_entries.flow.async_configure(flow["flow_id"], {**data, "api_key": "", "location": "113.00,28.00", "interval": 1200})
            assert result["type"] == "abort" and result["reason"] == "reconfigure_successful"
            await hass.async_block_till_done()
            assert entry.data["api_key"] == data["api_key"]
            assert entry.unique_id == "qweather_v1_28.0_113.0"
            assert registry.async_get("weather.zhangsha").id == legacy.id
            assert len(hass.states.async_all("weather")) == 1
            assert len(active()) == 1 and active()[0]["interval"] == 60
            assert await hass.config_entries.async_unload(entry.entry_id)
            await hass.async_block_till_done()
            assert not active()
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
            assert len(active()) == 1
            print("Reconfigure, blank key preservation, stable entity ID, unload/reload OK", flush=True)

            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives import serialization
            private = root / "jwt-private.pem"
            private.write_bytes(Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            flow = await hass.config_entries.flow.async_init("qweather", context={"source":"reconfigure", "entry_id":entry.entry_id})
            result = await hass.config_entries.flow.async_configure(flow["flow_id"], {**data, "auth_type":"jwt", "api_key":"", "key_id":"test-kid", "developer_id":"test-iss", "project_id":"test-sub", "private_key_file":str(private)})
            assert result["reason"] == "reconfigure_successful"
            await hass.async_block_till_done()
            assert entry.data["auth_type"] == "jwt" and "api_key" not in entry.data
            assert entry.state.value == "loaded" and len(active()) == 1
            assert registry.async_get("weather.zhangsha").id == legacy.id
            flow = await hass.config_entries.flow.async_init("qweather", context={"source":"reconfigure", "entry_id":entry.entry_id})
            result = await hass.config_entries.flow.async_configure(flow["flow_id"], {**data, "auth_type":"api_key"})
            assert result["reason"] == "reconfigure_successful"
            await hass.async_block_till_done()
            assert "private_key_file" not in entry.data and entry.data["api_key"] == data["api_key"]
            print("API Key/JWT switching, obsolete credential removal and stable entity identity OK", flush=True)

            # Restore the original coordinates and prove legacy YAML imports once.
            assert await hass.config_entries.async_remove(entry.entry_id)
            await hass.async_block_till_done()
            yaml_config = {**data, "platform": "qweather", "scan_interval": 600}
            yaml_config.pop("interval")
            # Re-run the platform setup through its validated YAML schema.
            from custom_components.qweather.weather import PLATFORM_SCHEMA, async_setup_platform
            await async_setup_platform(hass, PLATFORM_SCHEMA(yaml_config), None)
            await hass.async_block_till_done()
            imported_entries = hass.config_entries.async_entries("qweather")
            assert len(imported_entries) == 1 and imported_entries[0].source == "import"
            assert imported_entries[0].data["interval"] == 600
            assert imported_entries[0].state.value == "loaded"
            print("Automatic YAML import and preserved update interval OK", flush=True)
    finally:
        await hass.async_stop()
        shutil.rmtree(root)


asyncio.run(main())
