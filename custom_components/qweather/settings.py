"""Shared validation for UI configuration and legacy YAML imports."""
from .api import coordinates, validate_host

DEFAULTS = {"name": "和风天气", "default": 7, "hours": 24, "extras": [], "interval": 1800}
OPTIONS = ("name", "default", "hours", "extras", "interval")


def normalize(data):
    result = {**DEFAULTS, **data}
    latitude, longitude = coordinates(result["location"])
    result["location"] = f"{longitude:.2f},{latitude:.2f}"
    result["api_host"] = validate_host(result["api_host"])
    result["api_key"] = str(result["api_key"]).strip()
    result["name"] = str(result["name"]).strip()
    if not result["name"] or not result["api_key"]:
        raise ValueError("Name and key required")
    for key, low, high in (("default", 1, 10), ("hours", 1, 240), ("interval", 300, 86400)):
        result[key] = int(result[key])
        if not low <= result[key] <= high:
            raise ValueError("Invalid range")
    if not isinstance(result["extras"], list) or any(x not in ("air", "alerts", "minutely") for x in result["extras"]):
        raise ValueError("Invalid products")
    result["extras"] = list(dict.fromkeys(result["extras"]))
    return result


def location_id(data):
    latitude, longitude = coordinates(data["location"])
    return f"qweather_v1_{latitude}_{longitude}"
