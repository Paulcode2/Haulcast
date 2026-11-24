"""Phase 7 focused regression gaps (no duplication of existing coverage).

Covers at the API level, through the real pipeline:
- trips whose ETAs fall beyond forecast coverage,
- weather provider timeout through analyze (checkpoints + corridor),
- 10-mile interval short final segment via the endpoint,
- long-trip batching, sample bounds and response size,
- fewer than three routes with a real recommendation.
"""
import json
from unittest.mock import Mock, patch

import requests

from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIClient

from .corridor import MAX_CORRIDOR_POINTS
from .test_trips import route as here_route
from .test_weather import forecast


@override_settings(ALLOWED_HOSTS=["testserver"])
class Phase07APITests(SimpleTestCase):
    def post(self, payload):
        return APIClient().post("/api/trips/analyze", payload, format="json")

    @patch("api.weather.requests.get")
    @patch("api.views.fetch_trip")
    def test_eta_beyond_forecast_range_is_unavailable_not_low(self, trip, get):
        trip.return_value = ([{}, {}], [here_route(3, duration=600)])
        get.return_value.json.return_value = [forecast(), forecast()]
        response = self.post({"origin": "A", "destination": "B",
                              "departure_time": "2026-11-25T12:00:00Z",
                              "load_weight_lbs": 100})
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["weather_coverage"], {"complete": 0, "partial": 0, "unavailable": 2})
        for point in result["routes"][0]["checkpoints"]:
            self.assertEqual(point["risk"]["level"], "Unknown")
            self.assertEqual(point["weather"]["coverage"]["status"], "unavailable")
        self.assertIsNone(result["recommended_route_id"])
        self.assertEqual(result["recommendation"]["status"], "no_recommendation")

    @patch("api.weather.requests.get", side_effect=requests.Timeout())
    @patch("api.views.fetch_trip")
    def test_weather_timeout_gives_unavailable_checkpoints_and_corridor(self, trip, get):
        trip.return_value = ([{}, {}], [here_route(3, duration=600)])
        response = self.post({"origin": "A", "destination": "B",
                              "departure_time": "2026-11-25T08:00:00Z",
                              "load_weight_lbs": 100})
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["weather_coverage"]["unavailable"], 2)
        self.assertEqual(result["routes"][0]["checkpoints"][0]["risk"]["level"], "Unknown")
        corridor = result["corridor_forecast"]
        self.assertGreater(corridor["sample_count"], 0)
        self.assertTrue(all(level == "Unavailable"
                            for point in corridor["points"] for level in point["risk_levels"]))
        self.assertIsNone(result["recommended_route_id"])

    @patch("api.views.enrich_routes", return_value={"complete": 0, "partial": 0, "unavailable": 0})
    @patch("api.views.build_corridor_forecast",
           return_value={"forecast_reference_time": "2026-11-25T08:00:00Z", "timezone": "UTC",
                         "hour_count": 49, "timestamps": [], "sample_count": 0,
                         "truncated": False, "points": []})
    @patch("api.views.fetch_trip")
    def test_ten_mile_interval_short_final_segment_via_api(self, trip, corridor, weather):
        trip.return_value = ([{}, {}], [here_route(67)])
        response = self.post({"origin": "A", "destination": "B",
                              "departure_time": "2026-11-25T08:00:00Z",
                              "load_weight_lbs": 100, "checkpoint_interval_miles": 10})
        self.assertEqual(response.status_code, 200)
        points = response.json()["routes"][0]["checkpoints"]
        self.assertEqual([p["distance_miles"] for p in points],
                         [0, 10, 20, 30, 40, 50, 60, 67])
        self.assertAlmostEqual(points[-1]["distance_miles"] - points[-2]["distance_miles"], 7)
        self.assertEqual(points[-1]["eta"], response.json()["routes"][0]["destination_eta"])

    @patch("api.weather.requests.get")
    @patch("api.views.fetch_trip")
    def test_long_trip_batches_bound_samples_and_response_size(self, trip, get):
        trip.return_value = ([{}, {}], [here_route(500, duration=36000)])

        def fake_get(url, params=None, timeout=None):
            count = len(params["latitude"].split(","))
            resp = Mock()
            resp.json.return_value = [forecast() for _ in range(count)]
            resp.raise_for_status.return_value = None
            return resp

        get.side_effect = fake_get
        response = self.post({"origin": "A", "destination": "B",
                              "departure_time": "2026-11-25T08:00:00Z",
                              "load_weight_lbs": 100, "checkpoint_interval_miles": 50})
        self.assertEqual(response.status_code, 200)
        result = response.json()
        # 500 miles at 50-mile intervals: 0, 50, ..., 500.
        self.assertEqual(len(result["routes"][0]["checkpoints"]), 11)
        self.assertLessEqual(result["corridor_forecast"]["sample_count"], MAX_CORRIDOR_POINTS)
        # Checkpoints (1 batch) + corridor samples (multiple batches).
        self.assertGreaterEqual(get.call_count, 2)
        size = len(json.dumps(result).encode())
        self.assertGreater(size, 10000)
        # Response must stay bounded by the corridor cap, not grow with raw mileage.
        self.assertLess(size, 5_000_000)

    @patch("api.weather.requests.get")
    @patch("api.views.fetch_trip")
    def test_two_routes_return_recommendation(self, trip, get):
        trip.return_value = ([{}, {}], [here_route(67), here_route(70, "alternative")])

        def fake_get(url, params=None, timeout=None):
            count = len(params["latitude"].split(","))
            resp = Mock()
            resp.json.return_value = [forecast() for _ in range(count)]
            resp.raise_for_status.return_value = None
            return resp

        get.side_effect = fake_get
        response = self.post({"origin": "A", "destination": "B",
                              "departure_time": "2026-11-25T08:00:00Z",
                              "load_weight_lbs": 100})
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["route_count"], 2)
        self.assertIn(result["recommended_route_id"], ("primary", "alternative"))
        self.assertEqual(result["recommendation"]["status"], "recommended")
