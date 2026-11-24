import math
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import flexpolyline
import requests
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIClient

from .providers import TripError, fetch_trip, provider_json
from .routing import EARTH_RADIUS_M, METRES_PER_MILE, checkpoints, cumulative_distances, normalize_route

DEPARTURE = datetime(2026, 11, 25, 9, tzinfo=timezone(timedelta(hours=1)))


def point_at(miles):
    return (0.0, math.degrees(miles * METRES_PER_MILE / EARTH_RADIUS_M))


def route(miles=67, route_id="primary", duration=4020):
    return {"id": route_id, "sections": [{"polyline": flexpolyline.encode([point_at(0), point_at(miles)], precision=7),
            "summary": {"length": miles * METRES_PER_MILE, "duration": duration}}]}


class CheckpointTests(SimpleTestCase):
    def test_67_miles_all_intervals_and_destination_eta(self):
        points = [point_at(0), point_at(20), point_at(67)]
        distances = cumulative_distances(points)
        for interval, expected in [(10, [0, 10, 20, 30, 40, 50, 60, 67]), (25, [0, 25, 50, 67]), (50, [0, 50, 67])]:
            with self.subTest(interval=interval):
                result = checkpoints(points, distances, [0, 1200, 4020], DEPARTURE, interval)
                self.assertEqual([p["distance_miles"] for p in result], expected)
                times = [datetime.fromisoformat(p["eta"]) for p in result]
                self.assertTrue(all(a < b for a, b in zip(times, times[1:])))
                self.assertEqual(times[0], DEPARTURE)
                self.assertEqual(times[-1], DEPARTURE + timedelta(seconds=4020))
                self.assertEqual(result[-1]["longitude"], points[-1][1])

    def test_exact_multiple_has_one_destination_for_every_interval(self):
        for interval in (10, 25, 50):
            points = [point_at(0), point_at(interval * 2)]
            result = checkpoints(points, cumulative_distances(points), [0, 600], DEPARTURE, interval)
            self.assertEqual([p["distance_miles"] for p in result], [0, interval, interval * 2])

    def test_short_route_includes_both_endpoints(self):
        normalized, _ = normalize_route(route(3), DEPARTURE, 25)
        self.assertEqual(len(normalized["checkpoints"]), 2)
        self.assertEqual(normalized["checkpoints"][-1]["eta"], normalized["destination_eta"])

    def test_checkpoint_follows_bent_route_not_origin_chord(self):
        angle = point_at(25)[1]
        points = [(0, 0), (0, angle), (angle, angle)]
        result = checkpoints(points, cumulative_distances(points), [0, 600, 1200], DEPARTURE, 25)
        self.assertEqual(len(result), 3)
        self.assertAlmostEqual(result[1]["latitude"], 0)
        self.assertAlmostEqual(result[1]["longitude"], angle)

    def test_antimeridian_uses_short_segment(self):
        points = [(0, 179.8), (0, -179.8)]
        result = checkpoints(points, cumulative_distances(points), [0, 600], DEPARTURE, 10)
        self.assertTrue(all(abs(p["longitude"]) > 179 for p in result))

    def test_span_timing_is_not_uniform_speed(self):
        value = route(50, duration=3000)
        value["sections"][0]["polyline"] = flexpolyline.encode([point_at(0), point_at(25), point_at(50)], precision=7)
        value["sections"][0]["spans"] = [{"offset": 0, "duration": 600}, {"offset": 1, "duration": 2400}]
        normalized, _ = normalize_route(value, DEPARTURE, 25)
        midpoint_eta = datetime.fromisoformat(normalized["checkpoints"][1]["eta"])
        self.assertAlmostEqual((midpoint_eta - DEPARTURE).total_seconds(), 600, places=2)
        self.assertEqual(normalized["timing_methods"], ["span_duration_weights"])

    def test_sections_preserve_different_speeds_and_join_once(self):
        value = route(25, duration=600)
        value["sections"].append({"polyline": flexpolyline.encode([point_at(25), point_at(50)], precision=7), "summary": {"length": 25 * METRES_PER_MILE, "duration": 2400}})
        normalized, _ = normalize_route(value, DEPARTURE, 25)
        self.assertEqual(len(normalized["geometry"]["coordinates"]), 3)
        self.assertEqual(normalized["duration_seconds"], 3000)
        self.assertAlmostEqual((datetime.fromisoformat(normalized["checkpoints"][1]["eta"]) - DEPARTURE).total_seconds(), 600, places=2)

    def test_bad_span_metadata_falls_back(self):
        value = route()
        value["sections"][0]["spans"] = [{"offset": 99, "duration": 10}]
        normalized, _ = normalize_route(value, DEPARTURE, 25)
        self.assertEqual(normalized["timing_methods"], ["section_distance_approximation"])

    def test_invalid_geometry_is_safe_error(self):
        for value in ({"sections": []}, {"sections": [{"polyline": "invalid"}]}, route(0)):
            with self.subTest(value=value), self.assertRaises(TripError):
                normalize_route(value, DEPARTURE, 25)

    def test_geojson_order_and_geometry_distance_are_explicit(self):
        value = route()
        value["sections"][0]["polyline"] = flexpolyline.encode([(50, 8), (51, 9)])
        normalized, _ = normalize_route(value, DEPARTURE, 25)
        self.assertEqual(normalized["geometry"]["coordinates"][0], [8, 50])
        self.assertNotEqual(normalized["geometry_distance_miles"], normalized["distance_miles"])


@override_settings(ALLOWED_HOSTS=["testserver"])
class TripAPITests(SimpleTestCase):
    def setUp(self):
        self.client = APIClient()
        weather_patch = patch("api.views.enrich_routes", return_value={"complete": 0, "partial": 0, "unavailable": 0})
        weather_patch.start()
        self.addCleanup(weather_patch.stop)
        self.payload = {"origin": "Frankfurt am Main, Germany", "destination": "Kassel, Germany", "departure_time": DEPARTURE.isoformat(), "load_weight_lbs": 12000}

    def post(self, payload=None):
        return self.client.post("/api/trips/analyze", self.payload if payload is None else payload, format="json")

    @patch("api.views.fetch_trip")
    def test_success_defaults_and_returns_only_distinct_supplied_routes(self, fetch):
        fetch.return_value = ([{"label": "A"}, {"label": "B"}], [route(), route(route_id="duplicate"), route(70, "alternative")])
        response = self.post()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["route_count"], 2)
        self.assertEqual(data["checkpoint_interval_miles"], 25)
        self.assertEqual(data["weight_semantics"], "cargo_only")
        self.assertEqual(data["routes"][0]["id"], "primary")
        self.assertEqual(data["routes"][0]["destination_eta"], "2026-11-25T09:07:00Z")

    @patch("api.views.fetch_trip")
    def test_one_route_is_success(self, fetch):
        fetch.return_value = ([{}, {}], [route()])
        self.assertEqual(self.post().json()["route_count"], 1)

    @patch("api.views.fetch_trip")
    def test_three_distinct_routes_and_all_interval_requests(self, fetch):
        fetch.return_value = ([{}, {}], [route(67), route(70, "a"), route(75, "b")])
        for interval in (10, 25, 50):
            response = self.post({**self.payload, "checkpoint_interval_miles": interval})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["route_count"], 3)
            self.assertEqual(response.json()["routes"][0]["checkpoints"][1]["distance_miles"], interval)

    @patch("api.views.fetch_trip")
    def test_validation_rejects_inputs_before_provider_call(self, fetch):
        cases = {"origin": ["", "  ", None, 123, [], "a" * 501], "destination": ["", None],
                 "departure_time": ["2026-11-25T09:00:00", "2026-11-25", "2026-02-30T09:00:00+01:00", "2026-11-25T09:00:00+01:99", None],
                 "load_weight_lbs": [0, -1, "NaN", "Infinity", "-Infinity", "abc", True, None],
                 "checkpoint_interval_miles": [0, 11, 25.1, True, None]}
        for field, values in cases.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    response = self.post({**self.payload, field: value})
                    self.assertEqual(response.status_code, 400)
                    self.assertIn(field, response.json()["error"]["fields"])
        for field in self.payload:
            data = dict(self.payload)
            del data[field]
            self.assertEqual(self.post(data).status_code, 400)
        fetch.assert_not_called()

    @patch("api.views.fetch_trip")
    def test_utc_z_is_valid(self, fetch):
        fetch.return_value = ([{}, {}], [route()])
        self.assertEqual(self.post({**self.payload, "departure_time": "2026-11-25T09:00:00Z"}).status_code, 200)

    @patch("api.views.fetch_trip")
    def test_provider_errors_have_clear_responses(self, fetch):
        for code, status in [("geocoding_not_found", 422), ("no_routes", 422), ("provider_error", 502), ("provider_timeout", 504), ("provider_not_configured", 503)]:
            fetch.side_effect = TripError(code, "Safe message", status)
            response = self.post()
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.json()["error"]["code"], code)

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get("/api/trips/analyze").status_code, 405)


class ProviderTests(SimpleTestCase):
    @patch.dict("os.environ", {"HERE_API_KEY": "test-secret"})
    @patch("api.providers.provider_json")
    def test_request_contract_and_no_cargo_as_vehicle_weight(self, get):
        location = {"items": [{"title": "Place", "position": {"lat": 50, "lng": 8}}]}
        get.side_effect = [location, location, {"routes": [route()]}]
        fetch_trip("A", "B", DEPARTURE)
        params = get.call_args.args[1]
        self.assertEqual(params["transportMode"], "truck")
        self.assertEqual(params["alternatives"], 2)
        self.assertEqual(params["departureTime"], DEPARTURE.isoformat())
        self.assertIn("duration", params["spans"])
        self.assertFalse(any("weight" in key.lower() for key in params))

    @patch.dict("os.environ", {"HERE_API_KEY": ""})
    def test_missing_credentials(self):
        with self.assertRaises(TripError) as caught:
            fetch_trip("A", "B", DEPARTURE)
        self.assertEqual(caught.exception.status, 503)

    @patch.dict("os.environ", {"HERE_API_KEY": "test-secret"})
    @patch("api.providers.provider_json")
    def test_geocoding_failure_and_no_routes(self, get):
        location = {"items": [{"title": "Place", "position": {"lat": 50, "lng": 8}}]}
        for responses, code in [([{ "items": []}], "geocoding_not_found"), ([location, {"items": []}], "geocoding_not_found"), ([location, location, {"routes": []}], "no_routes"), ([{}], "invalid_provider_response")]:
            get.side_effect = responses
            with self.assertRaises(TripError) as caught:
                fetch_trip("A", "B", DEPARTURE)
            self.assertEqual(caught.exception.code, code)

    @patch("api.providers.requests.get")
    def test_http_status_diagnostics_never_expose_provider_body_or_key(self, get):
        for status in (400, 401, 403, 429):
            response = requests.Response()
            response.status_code = status
            get.side_effect = requests.HTTPError("apiKey=SECRET", response=response)
            with self.assertRaises(TripError) as caught:
                provider_json("https://example.com", {"apiKey": "SECRET"})
            self.assertEqual(caught.exception.status, 502)
            self.assertIn(f"HTTP {status}", caught.exception.message)
            self.assertNotIn("SECRET", caught.exception.message)

    @patch("api.providers.requests.get")
    def test_http_timeout_and_json_failures_are_sanitized(self, get):
        for exception, status in [(requests.Timeout("SECRET"), 504), (requests.HTTPError("SECRET"), 502), (requests.ConnectionError("SECRET"), 502), (ValueError("SECRET"), 502)]:
            get.side_effect = exception
            with self.assertRaises(TripError) as caught:
                provider_json("https://example.com", {"apiKey": "SECRET"})
            self.assertEqual(caught.exception.status, status)
            self.assertNotIn("SECRET", caught.exception.message)
