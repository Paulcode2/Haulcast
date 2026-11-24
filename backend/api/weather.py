"""Open-Meteo hourly forecasts and ETA matching; no departure-hour substitution."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import requests

from .risk import classify_risk, valid_value

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
BATCH_SIZE = 50
FIELDS = {"wind_mph": ("wind_speed_10m", "km/h", Decimal("1.609344")),
          "rain_in_per_hour": ("rain", "mm", Decimal("25.4")),
          "snow_in_per_hour": ("snowfall", "cm", Decimal("2.54"))}


def utc(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)  # Provider requested timezone=UTC.
    return parsed.astimezone(timezone.utc)


def iso(value):
    return value.isoformat().replace("+00:00", "Z")


def empty_weather(reason):
    return {"provider": "open-meteo", "forecast_timestamp": None,
            "field_timestamps": {name: None for name in FIELDS},
            "values": {name: None for name in FIELDS},
            "coverage": {"status": "unavailable", "missing_fields": list(FIELDS),
                         "issues": {name: reason for name in FIELDS}}}


def select_weather(forecast, eta):
    if not isinstance(forecast, dict):
        return empty_weather("invalid_provider_response")
    if "_error" in forecast:
        return empty_weather(forecast["_error"])
    try:
        if forecast.get("utc_offset_seconds") != 0:
            return empty_weather("unexpected_timezone")
        hourly = forecast["hourly"]
        times = [utc(t) for t in hourly["time"]]
        if not times or any(a >= b for a, b in zip(times, times[1:])):
            return empty_weather("invalid_forecast_timestamps")
        arrival = utc(eta)
        if arrival < times[0] or arrival > times[-1]:
            return empty_weather("eta_out_of_forecast_range")
        hour = arrival.replace(minute=0, second=0, microsecond=0)
        end = hour if arrival == hour else hour + timedelta(hours=1)
        wind_time = hour if arrival - hour < timedelta(minutes=30) else hour + timedelta(hours=1)
        indexes = {t: i for i, t in enumerate(times)}
        result = empty_weather("missing_hour")
        result["forecast_timestamp"] = iso(end) if end in indexes else None
        for name, (provider_field, expected_unit, divisor) in FIELDS.items():
            selected = wind_time if name == "wind_mph" else end
            index = indexes.get(selected)
            if index is None:
                continue
            result["field_timestamps"][name] = iso(selected)
            units = forecast.get("hourly_units", {})
            if not isinstance(units, dict) or units.get(provider_field) != expected_unit:
                result["coverage"]["issues"][name] = "unexpected_or_missing_unit"
                continue
            series = hourly.get(provider_field)
            value = series[index] if isinstance(series, list) and index < len(series) else None
            if not valid_value(value):
                result["coverage"]["issues"][name] = "missing_or_invalid_value"
                continue
            # Decimal conversion prevents binary arithmetic moving exact boundaries.
            result["values"][name] = float(Decimal(str(value)) / divisor)
            del result["coverage"]["issues"][name]
        missing = [name for name, value in result["values"].items() if value is None]
        result["coverage"]["missing_fields"] = missing
        result["coverage"]["status"] = "complete" if not missing else "unavailable" if len(missing) == 3 else "partial"
        return result
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return empty_weather("invalid_provider_response")


def coordinate_key(checkpoint):
    return (round(checkpoint["latitude"], 5), round(checkpoint["longitude"], 5))


def fetch_forecasts(coordinates):
    """Deduplicate across all routes; match ordered multi-location responses."""
    unique = list(dict.fromkeys(coordinates))
    forecasts = {}
    for start in range(0, len(unique), BATCH_SIZE):
        batch = unique[start:start + BATCH_SIZE]
        params = {"latitude": ",".join(str(p[0]) for p in batch),
                  "longitude": ",".join(str(p[1]) for p in batch),
                  "hourly": "wind_speed_10m,rain,snowfall", "wind_speed_unit": "kmh",
                  "precipitation_unit": "mm", "timezone": "UTC", "timeformat": "iso8601",
                  "forecast_days": 16}
        try:
            response = requests.get(FORECAST_URL, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            entries = data if isinstance(data, list) else [data]
            if len(entries) != len(batch) or any(not isinstance(entry, dict) or entry.get("error") for entry in entries):
                raise ValueError
            forecasts.update(zip(batch, entries))
        except requests.Timeout:
            forecasts.update((point, {"_error": "weather_provider_timeout"}) for point in batch)
        except requests.RequestException:
            forecasts.update((point, {"_error": "weather_provider_error"}) for point in batch)
        except ValueError:
            forecasts.update((point, {"_error": "invalid_provider_response"}) for point in batch)
    return forecasts


def enrich_routes(routes, load_weight_lbs):
    checkpoints = [point for route in routes for point in route["checkpoints"]]
    forecasts = fetch_forecasts([coordinate_key(point) for point in checkpoints])
    for point in checkpoints:
        weather = select_weather(forecasts[coordinate_key(point)], point["eta"])
        weather["requested_coordinates"] = dict(zip(("latitude", "longitude"), coordinate_key(point)))
        point["weather"] = weather
        point["risk"] = classify_risk(load_weight_lbs=load_weight_lbs, **weather["values"])
    return {"complete": sum(p["weather"]["coverage"]["status"] == "complete" for p in checkpoints),
            "partial": sum(p["weather"]["coverage"]["status"] == "partial" for p in checkpoints),
            "unavailable": sum(p["weather"]["coverage"]["status"] == "unavailable" for p in checkpoints)}
