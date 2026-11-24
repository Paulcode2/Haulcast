"""Corridor heatmap forecasts: samples along/around routes, hourly 0..48 from an explicit reference."""
import bisect
import math
from datetime import timedelta, timezone
from decimal import Decimal

from .ranking import RISK_SCALE
from .risk import classify_risk
from .weather import FIELDS, fetch_forecasts, iso, utc

FORECAST_HOURS = 49  # Hours 0..48 inclusive.
MAX_CORRIDOR_POINTS = 250
STEP_MILES = 5
LATERAL_MILES = (0, 6, -6)
MILES_PER_DEG_LAT = 69.0


def forecast_reference_time(departure):
    """Hour 0 is the departure hour floored to UTC; explicit and deterministic."""
    return departure.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def _cumulative(points):
    from .routing import distance
    result = [0.0]
    for a, b in zip(points, points[1:]):
        result.append(result[-1] + distance(a, b))
    return result


def _interpolate(points, distances, target):
    index = min(bisect.bisect_right(distances, target) - 1, len(points) - 2)
    span = distances[index + 1] - distances[index]
    ratio = (target - distances[index]) / span if span else 0
    a, b = points[index], points[index + 1]
    dlat = b[0] - a[0]
    dlng = (b[1] - a[1] + 180) % 360 - 180
    lat = a[0] + ratio * dlat
    lng = (a[1] + ratio * dlng + 180) % 360 - 180
    cos_lat = math.cos(math.radians((a[0] + b[0]) / 2))
    return (lat, lng), (dlng * cos_lat, dlat)


def _offset(point, direction, offset_miles):
    if offset_miles == 0:
        return point
    dx, dy = direction
    length = math.hypot(dx, dy)
    if length <= 0:
        return point
    perp_x, perp_y = -dy / length, dx / length
    lat, lng = point
    cos_lat = max(math.cos(math.radians(lat)), 0.2)
    return (lat + perp_y * offset_miles / MILES_PER_DEG_LAT,
            lng + perp_x * offset_miles / (MILES_PER_DEG_LAT * cos_lat))


def sample_corridor_points(routes, step_miles=STEP_MILES,
                            lateral_miles=LATERAL_MILES, max_points=MAX_CORRIDOR_POINTS):
    """Sample along each route geometry plus lateral offsets; dedupe nearby; bound count."""
    from .routing import METRES_PER_MILE
    collected = []
    for route in routes:
        coords = (route.get("geometry") or {}).get("coordinates") or []
        points = [(lat, lng) for lng, lat in coords
                  if isinstance(lat, (int, float)) and isinstance(lng, (int, float))
                  and not isinstance(lat, bool) and not isinstance(lng, bool)
                  and math.isfinite(lat) and math.isfinite(lng)]
        if len(points) < 2:
            continue
        distances = _cumulative(points)
        total_miles = distances[-1] / METRES_PER_MILE
        if total_miles <= 0:
            continue
        target = 0.0
        while target < distances[-1]:
            centre, direction = _interpolate(points, distances, target)
            for lateral in lateral_miles:
                collected.append(_offset(centre, direction, lateral))
            target += step_miles * METRES_PER_MILE
        end, _ = _interpolate(points, distances, distances[-1])
        collected.append(end)
    deduped, seen = [], set()
    for lat, lng in collected:
        key = (round(lat, 4), round(lng, 4))
        if key not in seen:
            seen.add(key)
            deduped.append((round(lat, 6), round(lng, 6)))
    truncated = len(deduped) > max_points
    if truncated:
        stride = math.ceil(len(deduped) / max_points)
        deduped = deduped[::stride][:max_points]
    return deduped, truncated


def _hourly_arrays(forecast, reference, load_weight_lbs):
    """Convert one Open-Meteo response into 49 hourly entries from reference."""
    blank = {"wind_mph": [None] * FORECAST_HOURS, "rain_in_per_hour": [None] * FORECAST_HOURS,
             "snow_in_per_hour": [None] * FORECAST_HOURS,
             "risk_levels": ["Unavailable"] * FORECAST_HOURS,
             "intensities": [None] * FORECAST_HOURS}
    if not isinstance(forecast, dict) or "_error" in forecast:
        return blank
    try:
        if forecast.get("utc_offset_seconds") != 0:
            return blank
        hourly = forecast["hourly"]
        times = [utc(t) for t in hourly["time"]]
        if not times or any(a >= b for a, b in zip(times, times[1:])):
            return blank
        index = {t: i for i, t in enumerate(times)}
        unit_map = forecast.get("hourly_units", {})
        if not isinstance(unit_map, dict):
            return blank
        stamps = [reference + timedelta(hours=h) for h in range(FORECAST_HOURS)]
        for h, stamp in enumerate(stamps):
            i = index.get(stamp)
            if i is None:
                continue
            values = {}
            usable = True
            for name, (field, expected_unit, divisor) in FIELDS.items():
                if unit_map.get(field) != expected_unit:
                    usable = False
                    break
                series = hourly.get(field)
                raw = series[i] if isinstance(series, list) and i < len(series) else None
                if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw) or raw < 0:
                    usable = False
                    break
                values[name] = float(Decimal(str(raw)) / divisor)
            if not usable:
                continue
            try:
                level = classify_risk(load_weight_lbs=load_weight_lbs, **{
                    name: values.get(name) for name in FIELDS})["level"]
            except ValueError:
                continue
            if level == "Unknown":
                continue
            blank["wind_mph"][h] = values.get("wind_mph")
            blank["rain_in_per_hour"][h] = values.get("rain_in_per_hour")
            blank["snow_in_per_hour"][h] = values.get("snow_in_per_hour")
            blank["risk_levels"][h] = level
            blank["intensities"][h] = RISK_SCALE[level] / 4
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return blank
    return blank


def empty_corridor(reference):
    stamps = [reference + timedelta(hours=h) for h in range(FORECAST_HOURS)]
    return {"forecast_reference_time": iso(reference), "timezone": "UTC",
            "hour_count": FORECAST_HOURS, "timestamps": [iso(t) for t in stamps],
            "sample_count": 0, "truncated": False, "points": []}


def build_corridor_forecast(routes, departure, load_weight_lbs):
    """Sample the corridor, fetch hourly forecasts in batches, keep all 49 hours for React."""
    reference = forecast_reference_time(departure)
    samples, truncated = sample_corridor_points(routes)
    if not samples:
        return empty_corridor(reference)
    forecasts = fetch_forecasts(samples)
    stamps = [reference + timedelta(hours=h) for h in range(FORECAST_HOURS)]
    points = []
    for lat, lng in samples:
        arrays = _hourly_arrays(forecasts.get((lat, lng)), reference, load_weight_lbs)
        points.append({"latitude": lat, "longitude": lng, **arrays})
    return {"forecast_reference_time": iso(reference), "timezone": "UTC",
            "hour_count": FORECAST_HOURS, "timestamps": [iso(t) for t in stamps],
            "sample_count": len(points), "truncated": truncated, "points": points}
