"""Select a polling interval using Home Assistant's local time."""


def refresh_interval(settings, local_now):
    start, end = settings["night_start"], settings["night_end"]
    hour = local_now.hour
    night = start <= hour < end if start < end else hour >= start or hour < end
    if settings["night_enabled"] and start != end and night:
        return settings["night_interval"]
    return settings["interval"]
