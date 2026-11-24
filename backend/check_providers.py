"""Live Phase 1 checks; no application trip-analysis functionality.

Never print request URLs or provider error bodies: HERE query URLs contain secrets.
"""
import argparse
import hashlib
import json
import os
from datetime import datetime, timedelta, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import flexpolyline
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
HERE_GEOCODE = "https://geocode.search.hereapi.com/v1/geocode"
HERE_ROUTE = "https://router.hereapi.com/v8/routes"
WEATHER = "https://api.open-meteo.com/v1/forecast"
CANDIDATES = [
    ("Frankfurt am Main, Germany", "Kassel, Germany"),
    ("Berlin, Germany", "Hamburg, Germany"),
    ("Amsterdam, Netherlands", "Rotterdam, Netherlands"),
]


class CheckError(Exception):
    pass


def get_json(url, params):
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.HTTPError as exc:
        raise CheckError(f"Provider HTTP {exc.response.status_code}; check credentials, service access, quota and parameters.") from None
    except (requests.RequestException, ValueError):
        raise CheckError("Provider network, timeout, or JSON error (request URL suppressed).") from None


def geocode(query, key):
    data = get_json(HERE_GEOCODE, {"q": query, "limit": 1, "apiKey": key})
    if not data.get("items"):
        raise CheckError(f"No geocoding result for {query}")
    item = data["items"][0]
    return {"query": query, "title": item["title"], "position": item["position"], "routing_position": (item.get("access") or [item["position"]])[0]}


def route_summary(route):
    sections = route.get("sections", [])
    if not sections:
        raise CheckError("Route has no sections")
    coordinates = []
    for section in sections:
        points = flexpolyline.decode(section["polyline"])
        if len(points) < 2:
            raise CheckError("Route section has insufficient geometry")
        for point in points:
            coordinate = [round(point[0], 5), round(point[1], 5)]
            if not (-90 <= coordinate[0] <= 90 and -180 <= coordinate[1] <= 180):
                raise CheckError("Invalid geometry coordinates")
            if not coordinates or coordinate != coordinates[-1]:
                coordinates.append(coordinate)
        if section["summary"]["length"] <= 0 or section["summary"]["duration"] <= 0:
            raise CheckError("Invalid route distance or duration")
    return {
        "id": route["id"],
        "distance_m": sum(s["summary"]["length"] for s in sections),
        "duration_s": sum(s["summary"]["duration"] for s in sections),
        "geometry_sha256": hashlib.sha256(json.dumps(coordinates).encode()).hexdigest(),
        "geometry_points": len(coordinates),
        "sections": [{"polyline": s["polyline"], "summary": s["summary"], "departure": s.get("departure"), "arrival": s.get("arrival"), "notices": s.get("notices", [])} for s in sections],
    }


def check_here(origin, destination, departure, key):
    locations = [geocode(q, key) for q in (origin, destination)]
    positions = [f'{v["routing_position"]["lat"]},{v["routing_position"]["lng"]}' for v in locations]
    params = {"origin": positions[0], "destination": positions[1], "transportMode": "truck", "routingMode": "fast", "alternatives": 2, "return": "polyline,summary", "departureTime": departure}
    data = get_json(HERE_ROUTE, {**params, "apiKey": key})
    routes = [route_summary(r) for r in data.get("routes", [])]
    distinct = len({r["geometry_sha256"] for r in routes})
    return {"status": "passed" if len(routes) == 3 and distinct == 3 else "failed", "locations": locations, "request": params, "route_count": len(routes), "distinct_geometry_count": distinct, "routes": routes}


def check_weather():
    params = {"latitude": 50.1109, "longitude": 8.6821, "hourly": "wind_speed_10m,rain,snowfall", "wind_speed_unit": "kmh", "precipitation_unit": "mm", "timeformat": "iso8601", "timezone": "UTC", "forecast_days": 2}
    data = get_json(WEATHER, params)
    expected = {"time": "iso8601", "wind_speed_10m": "km/h", "rain": "mm", "snowfall": "cm"}
    if data.get("hourly_units") != expected or data.get("utc_offset_seconds") != 0:
        raise CheckError("Unexpected weather units or UTC offset")
    hourly = data["hourly"]
    stamps = [datetime.fromisoformat(t) for t in hourly["time"]]
    if len(stamps) != 48 or any(b - a != timedelta(hours=1) for a, b in zip(stamps, stamps[1:])):
        raise CheckError("Expected 48 consecutive hourly timestamps")
    for field in ("wind_speed_10m", "rain", "snowfall"):
        values = hourly[field]
        if len(values) != len(stamps) or any(not isinstance(v, (float, int)) or v < 0 for v in values):
            raise CheckError(f"Invalid hourly data: {field}")
    return {"status": "passed", "request": params, "response": data}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["all", "here", "weather"], default="all")
    parser.add_argument("--origin", default=CANDIDATES[0][0])
    parser.add_argument("--destination", default=CANDIDATES[0][1])
    parser.add_argument("--departure", help="RFC3339 timestamp with explicit UTC offset")
    parser.add_argument("--timezone", default="Europe/Berlin")
    parser.add_argument("--search-demo", action="store_true", help="Try three candidate corridors; stop on three distinct routes")
    parser.add_argument("--output", default="../docs/testing/results/providers.json")
    args = parser.parse_args()
    zone = ZoneInfo(args.timezone)
    departure = args.departure or datetime.combine(datetime.now(zone).date() + timedelta(days=1), time(9), zone).isoformat()
    parsed = datetime.fromisoformat(departure)
    if parsed.utcoffset() is None or parsed.astimezone(zone).utcoffset() != parsed.utcoffset():
        parser.error("Departure must include an offset consistent with --timezone")
    report = {"checked_at_utc": datetime.now(timezone.utc).isoformat(), "departure": departure, "timezone": args.timezone}
    if args.provider in ("all", "weather"):
        try:
            report["weather"] = check_weather()
        except (CheckError, KeyError, TypeError, ValueError) as exc:
            report["weather"] = {"status": "failed", "reason": str(exc)}
    if args.provider in ("all", "here"):
        key = os.getenv("HERE_API_KEY", "").strip()
        if not key:
            report["here"] = {"status": "blocked", "reason": "Missing HERE_API_KEY; geocoding, routes and three-route demo are NOT live verified."}
        else:
            attempts = []
            for origin, destination in (CANDIDATES if args.search_demo else [(args.origin, args.destination)]):
                try:
                    attempt = check_here(origin, destination, departure, key)
                except (CheckError, KeyError, TypeError, ValueError) as exc:
                    attempt = {"status": "failed", "reason": str(exc), "origin": origin, "destination": destination}
                attempts.append(attempt)
                if attempt["status"] == "passed":
                    break
            report["here"] = {"status": attempts[-1]["status"], "attempts": attempts}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    for name in ("here", "weather"):
        if name in report:
            print(f'{name}: {report[name]["status"]} {report[name].get("reason", "")}')
    print(f"Evidence: {output.resolve()}")
    states = [report[k]["status"] for k in ("here", "weather") if k in report]
    return 1 if "failed" in states else 2 if "blocked" in states else 0


if __name__ == "__main__":
    raise SystemExit(main())
