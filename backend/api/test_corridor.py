from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIClient

from .corridor import (FORECAST_HOURS, MAX_CORRIDOR_POINTS, build_corridor_forecast,
                       forecast_reference_time, sample_corridor_points)
from .test_trips import DEPARTURE, route as here_route
from .test_weather import forecast


def corridor_forecast(hours=49, start=8, wind_kmh=0.0, rain_mm=0.0, snow_cm=0.0):
    base = datetime(2026, 11, 25, tzinfo=timezone.utc) + timedelta(hours=start)
    return {"utc_offset_seconds": 0,
            "hourly_units": {"wind_speed_10m": "km/h", "rain": "mm", "snowfall": "cm"},
            "hourly": {"time": [(base + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(hours)],
                       "wind_speed_10m": [wind_kmh] * hours,
                       "rain": [rain_mm] * hours, "snowfall": [snow_cm] * hours}}


def corridor_route(route_id="primary", miles=67, duration=4020):
    from .routing import normalize_route
    normalized, _ = __import__("api.routing", fromlist=["normalize_route"]).normalize_route(
        here_route(miles, route_id, duration), DEPARTURE, 25)
    return normalized


class CorridorSamplingTests(SimpleTestCase):
    def test_reference_time_floors_departure_hour_to_utc(self):
        self.assertEqual(forecast_reference_time(DEPARTURE).isoformat(), "2026-11-25T08:00:00+00:00")
        later = datetime(2026, 11, 25, 9, 45, tzinfo=timezone(timedelta(hours=1)))
        self.assertEqual(forecast_reference_time(later).isoformat(), "2026-11-25T08:00:00+00:00")

    def test_samples_cover_corridor_dedupe_and_bound(self):
        routes = [corridor_route("a"), corridor_route("a")]
        samples, truncated = sample_corridor_points(routes)
        self.assertGreater(len(samples), 3)
        self.assertEqual(len({(round(lat, 4), round(lng, 4)) for lat, lng in samples}), len(samples))
        self.assertLessEqual(len(samples), MAX_CORRIDOR_POINTS)
        self.assertFalse(truncated)
        many = [{"geometry": {"coordinates": [[-180 + i * 0.01, 0], [-180 + (i + 1) * 0.01, 0]]}} for i in range(400)]
        samples, truncated = sample_corridor_points(many)
        self.assertLessEqual(len(samples), MAX_CORRIDOR_POINTS)
        self.assertTrue(truncated)

    def test_lateral_offsets_widen_short_route(self):
        routes = [corridor_route("short", miles=3)]
        samples, _ = sample_corridor_points(routes)
        latitudes = {round(lat, 4) for lat, _ in samples}
        self.assertGreater(len(latitudes), 1)


class CorridorForecastTests(SimpleTestCase):
    @patch("api.corridor.fetch_forecasts")
    def test_hourly_arrays_cover_0_to_48_with_visible_levels(self, fetch):
        fetch.return_value = {(50.0, 8.0): corridor_forecast(wind_kmh=40.2336)}
        routes = [{"geometry": {"coordinates": [[8.0, 50.0], [8.0, 50.0]]}}]
        with patch("api.corridor.sample_corridor_points", return_value=([(50.0, 8.0)], False)):
            result = build_corridor_forecast(routes, DEPARTURE, 100)
        self.assertEqual(result["forecast_reference_time"], "2026-11-25T08:00:00Z")
        self.assertEqual(result["timezone"], "UTC")
        self.assertEqual(result["hour_count"], FORECAST_HOURS)
        self.assertEqual(len(result["timestamps"]), FORECAST_HOURS)
        self.assertEqual(result["timestamps"][0], "2026-11-25T08:00:00Z")
        self.assertEqual(result["timestamps"][-1], "2026-11-27T08:00:00Z")
        point = result["points"][0]
        self.assertEqual(len(point["risk_levels"]), FORECAST_HOURS)
        self.assertEqual(len(point["intensities"]), FORECAST_HOURS)
        self.assertTrue(all(level == "Moderate" for level in point["risk_levels"]))
        self.assertTrue(all(intensity == 0.25 for intensity in point["intensities"]))

    @patch("api.corridor.fetch_forecasts")
    def test_missing_hour_is_explicit_unavailable(self, fetch):
        data = corridor_forecast(hours=48, wind_kmh=40.2336)
        fetch.return_value = {(50.0, 8.0): data}
        routes = [{"geometry": {"coordinates": [[8.0, 50.0], [8.0, 50.0]]}}]
        with patch("api.corridor.sample_corridor_points", return_value=([(50.0, 8.0)], False)):
            result = build_corridor_forecast(routes, DEPARTURE, 100)
        point = result["points"][0]
        self.assertEqual(point["risk_levels"][-1], "Unavailable")
        self.assertIsNone(point["intensities"][-1])
        self.assertIsNone(point["wind_mph"][-1])

    @patch("api.corridor.fetch_forecasts")
    def test_provider_error_is_unavailable_not_zero(self, fetch):
        fetch.return_value = {(50.0, 8.0): {"_error": "weather_provider_timeout"}}
        routes = [{"geometry": {"coordinates": [[8.0, 50.0], [8.0, 50.0]]}}]
        with patch("api.corridor.sample_corridor_points", return_value=([(50.0, 8.0)], False)):
            result = build_corridor_forecast(routes, DEPARTURE, 100)
        point = result["points"][0]
        self.assertTrue(all(level == "Unavailable" for level in point["risk_levels"]))
        self.assertTrue(all(value is None for value in point["intensities"]))

    @patch("api.corridor.fetch_forecasts")
    def test_fetch_uses_deduped_samples_in_batches(self, fetch):
        fetch.return_value = {}
        routes = [corridor_route("a"), corridor_route("a")]
        build_corridor_forecast(routes, DEPARTURE, 100)
        requested = fetch.call_args.args[0]
        self.assertEqual(len(requested), len(set(requested)))
        self.assertLessEqual(len(requested), MAX_CORRIDOR_POINTS)


@override_settings(ALLOWED_HOSTS=["testserver"])
class CorridorAPITests(SimpleTestCase):
    @patch("api.weather.requests.get")
    @patch("api.views.fetch_trip")
    def test_analyze_includes_corridor_and_keeps_eta_risk(self, trip, get):
        trip.return_value = ([{}, {}], [here_route(3, duration=600)])
        data = forecast()
        get.return_value.json.return_value = [data, data]
        response = APIClient().post("/api/trips/analyze", {"origin": "A", "destination": "B", "departure_time": "2026-11-25T08:00:00Z", "load_weight_lbs": 100}, format="json")
        self.assertEqual(response.status_code, 200)
        result = response.json()
        corridor = result["corridor_forecast"]
        self.assertEqual(corridor["forecast_reference_time"], "2026-11-25T08:00:00Z")
        self.assertEqual(corridor["hour_count"], FORECAST_HOURS)
        self.assertEqual(len(corridor["timestamps"]), FORECAST_HOURS)
        self.assertGreater(corridor["sample_count"], 0)
        self.assertLessEqual(corridor["sample_count"], MAX_CORRIDOR_POINTS)
        self.assertEqual(len(corridor["points"][0]["risk_levels"]), FORECAST_HOURS)
        self.assertEqual(result["routes"][0]["checkpoints"][0]["risk"]["level"], "Low")
        self.assertEqual(result["routes"][0]["checkpoints"][0]["eta"], "2026-11-25T08:00:00Z")
