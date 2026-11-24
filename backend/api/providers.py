"""Backend-only HERE adapter; never expose keyed URLs or raw error bodies."""
import os
import math

import requests

from check_providers import HERE_GEOCODE, HERE_ROUTE


class TripError(Exception):
    def __init__(self, code, message, status=502):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def provider_json(url, params):
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError
        return data
    except requests.Timeout:
        raise TripError("provider_timeout", "HERE timed out. Please retry.", 504) from None
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        messages = {
            401: "HERE rejected the API key (HTTP 401). Replace HERE_API_KEY in backend/.env with a valid HERE API key and restart Django.",
            403: "HERE denied access (HTTP 403). Check the HERE application's service access and key restrictions.",
            429: "HERE rate limit or quota exceeded (HTTP 429). Check usage and retry later.",
            400: "HERE rejected the request parameters (HTTP 400). Check the locations, departure time and routing configuration.",
        }
        raise TripError("provider_error", messages.get(status, "HERE request failed. Check backend credentials, service access and quota.")) from None
    except requests.RequestException:
        raise TripError("provider_error", "HERE request failed. Check backend credentials, service access and quota.") from None
    except ValueError:
        raise TripError("invalid_provider_response", "HERE returned an invalid response.") from None


def geocode_location(query, key, field):
    data = provider_json(HERE_GEOCODE, {"q": query, "limit": 1, "apiKey": key})
    if data.get("items") == []:
        raise TripError("geocoding_not_found", f"Could not geocode {field}. Use a more specific location.", 422)
    try:
        item = data["items"][0]
        position = (item.get("access") or [item["position"]])[0]
        lat, lng = float(position["lat"]), float(position["lng"])
        if not math.isfinite(lat) or not math.isfinite(lng) or not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise ValueError
        return {"query": query, "label": item["title"], "latitude": lat, "longitude": lng}
    except (KeyError, IndexError, TypeError, ValueError):
        raise TripError("invalid_provider_response", "HERE returned invalid geocoding data.") from None


def fetch_trip(origin, destination, departure):
    key = os.getenv("HERE_API_KEY", "").strip()
    if not key:
        raise TripError("provider_not_configured", "Set HERE_API_KEY on the backend to enable routing.", 503)
    locations = [geocode_location(query, key, field) for query, field in ((origin, "origin"), (destination, "destination"))]
    positions = [f'{p["latitude"]},{p["longitude"]}' for p in locations]
    # Cargo alone is neither current vehicle weight nor legal gross weight.
    data = provider_json(HERE_ROUTE, {
        "apiKey": key, "origin": positions[0], "destination": positions[1],
        "transportMode": "truck", "routingMode": "fast", "alternatives": 2,
        "departureTime": departure.isoformat(), "return": "polyline,summary",
        "spans": "duration,length,segmentRef",
    })
    if not isinstance(data.get("routes"), list):
        raise TripError("invalid_provider_response", "HERE returned invalid routing data.")
    if not data["routes"]:
        raise TripError("no_routes", "No truck routes are available for these locations and departure.", 422)
    return locations, data["routes"]
