"""Geometry distance in metres; timing weights come from HERE spans/sections."""
import bisect
import hashlib
import json
import math
from datetime import timedelta, timezone

import flexpolyline

from .providers import TripError

METRES_PER_MILE = 1609.344
EARTH_RADIUS_M = 6371008.8
ENDPOINT_TOLERANCE_M = 0.1


def distance(a, b):
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlat = lat2 - lat1
    dlng = math.radians(b[1] - a[1])
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1, math.sqrt(h)))


def cumulative_distances(points):
    result = [0.0]
    for a, b in zip(points, points[1:]):
        result.append(result[-1] + distance(a, b))
    return result


def timestamp(departure, seconds):
    return (departure.astimezone(timezone.utc) + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def checkpoints(points, distances, elapsed, departure, interval):
    total = distances[-1]
    step = interval * METRES_PER_MILE
    targets = [0.0]
    current = step
    while current < total - ENDPOINT_TOLERANCE_M:
        targets.append(current)
        current += step
    targets.append(total)
    result = []
    for target in targets:
        index = min(bisect.bisect_right(distances, target) - 1, len(points) - 2)
        segment = distances[index + 1] - distances[index]
        ratio = (target - distances[index]) / segment if segment else 0
        a, b = points[index], points[index + 1]
        # Interpolate the short longitude direction across the antimeridian.
        delta_lng = (b[1] - a[1] + 180) % 360 - 180
        lat = a[0] + ratio * (b[0] - a[0])
        lng = (a[1] + ratio * delta_lng + 180) % 360 - 180
        seconds = elapsed[index] + ratio * (elapsed[index + 1] - elapsed[index])
        if target == 0:
            lat, lng, seconds = *points[0], 0
        elif target == total:
            lat, lng, seconds = *points[-1], elapsed[-1]
        result.append({"index": len(result), "distance_miles": round(target / METRES_PER_MILE, 6),
                       "latitude": lat, "longitude": lng, "eta": timestamp(departure, seconds)})
    return result


def section_elapsed(section, points, distances, duration):
    """Use span durations as relative timing weights, falling back to section distance."""
    spans = section.get("spans")
    if spans:
        try:
            offsets = [s["offset"] for s in spans] + [len(points) - 1]
            weights = [float(s["duration"]) for s in spans]
            if offsets[0] != 0 or any(type(i) is not int for i in offsets):
                raise ValueError
            if any(a >= b for a, b in zip(offsets, offsets[1:])) or offsets[-2] >= len(points) - 1:
                raise ValueError
            if any(not math.isfinite(w) or w <= 0 for w in weights):
                raise ValueError
            values = [0.0] * len(points)
            clock = 0.0
            for start, end, weight in zip(offsets, offsets[1:], weights):
                length = distances[end] - distances[start]
                if length <= 0:
                    raise ValueError
                seconds = weight / sum(weights) * duration
                for i in range(start, end + 1):
                    values[i] = clock + seconds * (distances[i] - distances[start]) / length
                clock += seconds
            values[-1] = duration
            return values, "span_duration_weights"
        except (KeyError, TypeError, ValueError, IndexError):
            pass
    return [duration * d / distances[-1] for d in distances], "section_distance_approximation"


def normalize_route(route, departure, interval):
    try:
        sections = route["sections"]
        if not sections:
            raise ValueError
        points, elapsed, methods = [], [], []
        total_duration, provider_distance = 0.0, 0.0
        for section in sections:
            decoded = [tuple(p[:2]) for p in flexpolyline.decode(section["polyline"])]
            if len(decoded) < 2 or any(not all(math.isfinite(v) for v in p) or not (-90 <= p[0] <= 90 and -180 <= p[1] <= 180) for p in decoded):
                raise ValueError
            duration = float(section["summary"]["duration"])
            length = float(section["summary"]["length"])
            if not all(math.isfinite(v) and v > 0 for v in (duration, length)):
                raise ValueError
            distances = cumulative_distances(decoded)
            if distances[-1] <= 0:
                raise ValueError
            times, method = section_elapsed(section, decoded, distances, duration)
            methods.append(method)
            if points and distance(points[-1], decoded[0]) > ENDPOINT_TOLERANCE_M:
                raise ValueError  # Never draw an invented connector between disconnected sections.
            for point, seconds in zip(decoded, times):
                if points and point == points[-1]:
                    continue
                points.append(point)
                elapsed.append(total_duration + seconds)
            total_duration += duration
            provider_distance += length
        elapsed[-1] = total_duration
        distances = cumulative_distances(points)
        geometry = {"type": "LineString", "coordinates": [[p[1], p[0]] for p in points]}
        digest = hashlib.sha256(json.dumps([[round(p[0], 5), round(p[1], 5)] for p in points]).encode()).hexdigest()
        return {"id": str(route.get("id") or digest[:16]), "distance_meters": provider_distance,
                "distance_miles": provider_distance / METRES_PER_MILE,
                "geometry_distance_miles": distances[-1] / METRES_PER_MILE,
                "duration_seconds": total_duration, "geometry": geometry,
                "destination_eta": timestamp(departure, total_duration),
                "timing_methods": list(dict.fromkeys(methods)),
                "checkpoints": checkpoints(points, distances, elapsed, departure, interval)}, digest
    except (KeyError, TypeError, ValueError, IndexError, OverflowError):
        raise TripError("invalid_provider_response", "HERE returned unusable route geometry or timing.") from None


def normalize_routes(routes, departure, interval):
    result, seen = [], set()
    for route in routes:
        normalized, digest = normalize_route(route, departure, interval)
        if digest not in seen:
            seen.add(digest)
            result.append(normalized)
    return result
