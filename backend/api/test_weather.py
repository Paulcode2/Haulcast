from copy import deepcopy
from unittest.mock import patch

import requests
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIClient

from .risk import classify_risk
from .weather import enrich_routes, fetch_forecasts, select_weather
from .test_trips import route


def forecast():
    return {"utc_offset_seconds": 0, "hourly_units": {"wind_speed_10m": "km/h", "rain": "mm", "snowfall": "cm"},
            "hourly": {"time": [f"2026-11-25T{hour:02d}:00" for hour in range(8, 12)],
                       "wind_speed_10m": [0, 40.2336, 88.51392, 0],
                       "rain": [0, 2.54, 25.4, 0], "snowfall": [0, 1.27, 7.62, 0]}}


class RiskTests(SimpleTestCase):
    def test_wind_boundaries(self):
        for value, expected in [(0, "Low"), (24.999, "Low"), (25, "Moderate"), (34.999, "Moderate"),
                                (35, "High"), (44.999, "High"), (45, "Severe"), (54.999, "Severe"), (55, "No Travel"), (60, "No Travel")]:
            with self.subTest(value=value):
                self.assertEqual(classify_risk(value, 0, 0, 100)["level"], expected)

    def test_rain_boundaries(self):
        for value, expected in [(0, "Low"), (.09999, "Low"), (.10, "Moderate"), (.24999, "Moderate"),
                                (.25, "High"), (.49999, "High"), (.50, "Severe"), (1, "Severe"), (1.00001, "No Travel")]:
            with self.subTest(value=value):
                self.assertEqual(classify_risk(0, value, 0, 100)["level"], expected)

    def test_snow_boundaries(self):
        for value, expected in [(0, "Low"), (.49999, "Low"), (.5, "Moderate"), (.99999, "Moderate"),
                                (1, "High"), (1.99999, "High"), (2, "Severe"), (3, "Severe"), (3.00001, "No Travel")]:
            with self.subTest(value=value):
                self.assertEqual(classify_risk(0, 0, value, 100)["level"], expected)

    def test_strict_load_overrides(self):
        for wind, weight, expected in [(45, 30000, "Severe"), (45, 30000.01, "No Travel"),
                                       (54.999, 30001, "No Travel"), (35, 40000, "High"),
                                       (35, 40000.01, "Severe"), (44.999, 40001, "Severe"),
                                       (34.999, 50000, "Moderate"), (55, 1, "No Travel"), (55, 50000, "No Travel")]:
            with self.subTest(wind=wind, weight=weight):
                self.assertEqual(classify_risk(wind, 0, 0, weight)["level"], expected)
        self.assertIn("cargo above", classify_risk(45, 300, 0, 30001)["reasons"][0])

    def test_highest_condition_and_tied_reasons(self):
        result = classify_risk(25, .5, 3, 100)
        self.assertEqual(result["level"], "Severe")
        self.assertEqual(result["triggering_conditions"], ["rain_in_per_hour", "snow_in_per_hour"])
        self.assertEqual(len(result["reasons"]), 2)

    def test_missing_fields_preserve_any_confirmed_no_travel(self):
        for values in [(55, None, 0), (None, 1.01, None), (None, None, 3.01), (45, None, None)]:
            with self.subTest(values=values):
                result = classify_risk(*values, 30001)
                self.assertEqual(result["level"], "No Travel")
                self.assertEqual(result["assessment_status"], "confirmed")
                self.assertFalse(result["coverage_complete"])

    def test_partial_low_is_incomplete_not_safe_and_all_missing_unknown(self):
        result = classify_risk(0, None, 0, 100)
        self.assertEqual(result["level"], "Low")
        self.assertEqual(result["assessment_status"], "incomplete")
        self.assertEqual(classify_risk(None, None, None, 100)["level"], "Unknown")

    def test_invalid_weather_is_missing_and_bad_load_rejected(self):
        for value in (-1, float("nan"), float("inf"), True, "55"):
            self.assertIn("wind_mph", classify_risk(value, 0, 0, 100)["missing_fields"])
        for value in (0, -1, float("nan"), float("inf"), True):
            with self.assertRaises(ValueError):
                classify_risk(0, 0, 0, value)


class ForecastSelectionTests(SimpleTestCase):
    def test_eta_uses_later_hour_than_departure_and_exact_conversions(self):
        result = select_weather(forecast(), "2026-11-25T11:00:00+01:00")
        self.assertEqual(result["values"], {"wind_mph": 55, "rain_in_per_hour": 1, "snow_in_per_hour": 3})
        self.assertEqual(result["forecast_timestamp"], "2026-11-25T10:00:00Z")
        self.assertEqual(result["coverage"]["status"], "complete")

    def test_wind_nearest_precipitation_following_interval_end(self):
        early = select_weather(forecast(), "2026-11-25T09:10:00Z")
        self.assertEqual(early["field_timestamps"]["wind_mph"], "2026-11-25T09:00:00Z")
        self.assertEqual(early["field_timestamps"]["rain_in_per_hour"], "2026-11-25T10:00:00Z")
        self.assertEqual(early["values"]["wind_mph"], 25)
        late = select_weather(forecast(), "2026-11-25T09:30:00Z")
        self.assertEqual(late["values"]["wind_mph"], 55)

    def test_exact_hour_uses_preceding_precipitation_hour(self):
        result = select_weather(forecast(), "2026-11-25T09:00:00Z")
        self.assertEqual(result["values"], {"wind_mph": 25, "rain_in_per_hour": .1, "snow_in_per_hour": .5})

    def test_out_of_range_never_clamped(self):
        for eta in ("2026-11-25T07:59:59Z", "2026-11-25T11:00:01Z", "2027-01-01T00:00:00Z"):
            result = select_weather(forecast(), eta)
            self.assertEqual(result["coverage"]["status"], "unavailable")
            self.assertIsNone(result["forecast_timestamp"])
            self.assertEqual(set(result["coverage"]["issues"].values()), {"eta_out_of_forecast_range"})

    def test_missing_null_invalid_values_and_units_do_not_erase_wind(self):
        for invalid in (None, -1, float("nan"), float("inf"), "2", True):
            data = forecast()
            data["hourly"]["rain"][2] = invalid
            result = select_weather(data, "2026-11-25T10:00:00Z")
            self.assertIsNone(result["values"]["rain_in_per_hour"])
            self.assertEqual(result["values"]["wind_mph"], 55)
            self.assertEqual(result["coverage"]["status"], "partial")
        data = forecast()
        data["hourly_units"]["snowfall"] = "mm"
        del data["hourly"]["rain"]
        result = select_weather(data, "2026-11-25T10:00:00Z")
        self.assertEqual(result["values"]["wind_mph"], 55)
        self.assertEqual(len(result["coverage"]["missing_fields"]), 2)

    def test_missing_hour_and_short_array(self):
        data = forecast()
        data["hourly"]["time"][1] = "2026-11-25T09:01:00"
        data["hourly"]["rain"] = []
        result = select_weather(data, "2026-11-25T09:10:00Z")
        self.assertEqual(result["coverage"]["issues"]["wind_mph"], "missing_hour")
        self.assertEqual(result["coverage"]["issues"]["rain_in_per_hour"], "missing_or_invalid_value")

    def test_malformed_timestamp_and_wrong_timezone(self):
        for data in ({}, [], {"utc_offset_seconds": 3600}, {"utc_offset_seconds": 0, "hourly": {"time": ["bad"]}}):
            self.assertEqual(select_weather(data, "2026-11-25T10:00:00Z")["coverage"]["status"], "unavailable")

    def test_utc_midnight_precipitation_window(self):
        data = forecast()
        data["hourly"]["time"] = ["2026-11-25T23:00", "2026-11-26T00:00", "2026-11-26T01:00", "2026-11-26T02:00"]
        result = select_weather(data, "2026-11-26T00:45:00+01:00")
        self.assertEqual(result["forecast_timestamp"], "2026-11-26T00:00:00Z")
        self.assertEqual(result["values"]["rain_in_per_hour"], .1)

    def test_selection_does_not_mutate_forecast(self):
        data = forecast()
        original = deepcopy(data)
        select_weather(data, "2026-11-25T10:00:00Z")
        self.assertEqual(data, original)


class WeatherFetchTests(SimpleTestCase):
    @patch("api.weather.requests.get")
    def test_deduplication_batching_and_parameter_contract(self, get):
        get.return_value.json.return_value = [forecast(), forecast()]
        result = fetch_forecasts([(50, 8), (50, 8), (51, 9)])
        self.assertEqual(len(result), 2)
        get.assert_called_once()
        params = get.call_args.kwargs["params"]
        self.assertEqual(params["latitude"], "50,51")
        self.assertEqual(params["longitude"], "8,9")
        self.assertEqual(params["timezone"], "UTC")
        self.assertEqual(params["hourly"], "wind_speed_10m,rain,snowfall")

    @patch("api.weather.requests.get")
    def test_multiple_batches_and_single_location_object(self, get):
        get.return_value.json.side_effect = [[forecast()] * 50, forecast()]
        result = fetch_forecasts([(i, 0) for i in range(51)])
        self.assertEqual(get.call_count, 2)
        self.assertEqual(len(result), 51)

    @patch("api.weather.requests.get")
    def test_network_and_bad_batch_failures_are_unavailable(self, get):
        for error in (requests.Timeout(), requests.ConnectionError(), requests.HTTPError(), ValueError()):
            get.side_effect = error
            result = fetch_forecasts([(50, 8)])
            self.assertIn("_error", result[(50, 8)])
        get.side_effect = None
        get.return_value.json.return_value = [forecast()]
        result = fetch_forecasts([(50, 8), (51, 9)])
        self.assertTrue(all("_error" in data for data in result.values()))

    @patch("api.weather.requests.get")
    def test_shared_coordinate_still_uses_individual_route_eta(self, get):
        get.return_value.json.return_value = forecast()
        routes = [{"checkpoints": [{"latitude": 50, "longitude": 8, "eta": "2026-11-25T08:00:00Z"}]},
                  {"checkpoints": [{"latitude": 50, "longitude": 8, "eta": "2026-11-25T10:00:00Z"}]}]
        self.assertEqual(enrich_routes(routes, 100)["complete"], 2)
        get.assert_called_once()
        self.assertEqual(routes[0]["checkpoints"][0]["risk"]["level"], "Low")
        self.assertEqual(routes[1]["checkpoints"][0]["risk"]["level"], "No Travel")


@override_settings(ALLOWED_HOSTS=["testserver"])
class WeatherAPITests(SimpleTestCase):
    @patch("api.weather.requests.get")
    @patch("api.views.fetch_trip")
    def test_full_api_flow_with_mocked_forecasts_and_partial_no_travel(self, trip, get):
        trip.return_value = ([{}, {}], [route(3, duration=7200)])
        data = forecast()
        data["hourly"]["rain"][2] = None
        get.return_value.json.return_value = [data, data]
        response = APIClient().post("/api/trips/analyze", {"origin": "A", "destination": "B", "departure_time": "2026-11-25T08:00:00Z", "load_weight_lbs": 100}, format="json")
        self.assertEqual(response.status_code, 200)
        points = response.json()["routes"][0]["checkpoints"]
        self.assertEqual(points[0]["risk"]["level"], "Low")
        self.assertEqual(points[-1]["risk"]["level"], "No Travel")
        self.assertFalse(points[-1]["risk"]["coverage_complete"])
        self.assertEqual(points[-1]["weather"]["forecast_timestamp"], "2026-11-25T10:00:00Z")
        self.assertEqual(response.json()["weather_coverage"], {"complete": 1, "partial": 1, "unavailable": 0})

    @patch("api.weather.requests.get", side_effect=requests.Timeout())
    @patch("api.views.fetch_trip")
    def test_weather_outage_keeps_routes_but_never_claims_low_risk(self, trip, get):
        trip.return_value = ([{}, {}], [route(3)])
        response = APIClient().post("/api/trips/analyze", {"origin": "A", "destination": "B", "departure_time": "2026-11-25T08:00:00Z", "load_weight_lbs": 100}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["weather_coverage"]["unavailable"], 2)
        self.assertEqual(response.json()["routes"][0]["checkpoints"][0]["risk"]["level"], "Unknown")
