"""Translate documented v1 payloads into Home Assistant native units."""
import math
from datetime import datetime

from .condition import CONDITION_MAP, EXCEPTIONAL


def number(value):
    if value is None:
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Non-finite measurement")
    return result


def measure(data, key, unit):
    obj = data.get(key)
    if not obj:
        return None
    if obj.get("unit") != unit:
        raise ValueError(f"Unexpected unit for {key}")
    return number(obj.get("value"))


def percent(value):
    value = number(value)
    if value is not None and not 0 <= value <= 1:
        raise ValueError("Invalid fraction")
    return None if value is None else round(value * 100)


def condition(data):
    return CONDITION_MAP.get(str(data.get("condition", {}).get("code")), EXCEPTIONAL)


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Forecast timestamp has no timezone")
    return parsed.isoformat()


def current_attributes(data):
    temperature = measure(data, "temperature", "°C")
    if temperature is None or not isinstance(data.get("condition"), dict):
        raise ValueError("Missing current weather")
    return {
        "condition": condition(data),
        "native_temperature": temperature,
        "native_apparent_temperature": measure(data, "feelsLike", "°C"),
        "native_pressure": measure(data, "pressure", "hPa"),
        "native_visibility": measure(data, "visibility", "m"),
        "native_dew_point": measure(data, "dewPoint", "°C"),
        "native_wind_speed": measure(data.get("wind", {}), "speed", "m/s"),
        "wind_bearing": number(data.get("wind", {}).get("direction", {}).get("degree")),
        "humidity": percent(data.get("humidity")),
        "cloud_coverage": percent(data.get("cloudCover")),
        "uv_index": number(data.get("uvIndex")),
        "extra_state_attributes": {
            "condition_desc": data["condition"].get("text"),
            "attributions": data.get("metadata", {}).get("attributions", []),
        },
    }


def common_forecast(data):
    return {k: v for k, v in {
        "condition": condition(data),
        "native_wind_speed": measure(data.get("wind", {}), "speed", "m/s"),
        "wind_bearing": number(data.get("wind", {}).get("direction", {}).get("degree")),
        "humidity": percent(data.get("humidity")),
        "cloud_coverage": percent(data.get("cloudCover")),
        "precipitation_probability": percent(data.get("precipitation", {}).get("probability")),
    }.items() if v is not None}


def daily_forecasts(payload):
    rows = payload["days"]
    if not isinstance(rows, list) or not rows:
        raise ValueError("Missing daily forecast")
    result = []
    for row in rows:
        # Whole-day extrema and daytime condition. A daily precipitation
        # probability cannot be derived from two half-day probabilities.
        day = row.get("daytime", {})
        item = common_forecast(day)
        item.pop("precipitation_probability", None)
        item["datetime"] = timestamp(row["forecastStartTime"])
        item["native_temperature"] = measure(row, "temperatureMax", "°C")
        item["native_templow"] = measure(row, "temperatureMin", "°C")
        if item["native_temperature"] is None or item["native_templow"] is None:
            raise ValueError("Missing daily temperature")
        day_rain = measure(day.get("precipitation", {}), "amount", "mm")
        night_rain = measure(row.get("nighttime", {}).get("precipitation", {}), "amount", "mm")
        if day_rain is not None and night_rain is not None:
            item["native_precipitation"] = round(day_rain + night_rain, 3)
        result.append(item)
    return result


def hourly_forecasts(payload):
    rows = payload["hours"]
    if not isinstance(rows, list) or not rows:
        raise ValueError("Missing hourly forecast")
    result = []
    for row in rows:
        item = common_forecast(row)
        item["datetime"] = timestamp(row["forecastTime"])
        item["native_temperature"] = measure(row, "temperature", "°C")
        if item["native_temperature"] is None:
            raise ValueError("Missing hourly temperature")
        for key, value in {
            "native_pressure": measure(row, "pressure", "hPa"),
            "native_precipitation": measure(row.get("precipitation", {}), "amount", "mm"),
        }.items():
            if value is not None:
                item[key] = value
        result.append(item)
    return result
