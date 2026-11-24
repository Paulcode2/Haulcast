from copy import deepcopy
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIClient

from .ranking import RISK_SCALE, summarize_and_recommend, summarize_route
from .routing import METRES_PER_MILE
from .test_trips import route as here_route
from .test_weather import forecast


def fixture(route_id, distances, levels, duration=3600, incomplete=()):
    return {"id": route_id, "duration_seconds": duration,
            "checkpoints": [{"index": i, "distance_meters": miles * METRES_PER_MILE,
                             "distance_miles": round(miles, 6),
                             "risk": {"level": level, "coverage_complete": i not in incomplete and level != "Unknown"},
                             "weather": {"coverage": {"status": "partial" if i in incomplete else "unavailable" if level == "Unknown" else "complete"}}}
                            for i, (miles, level) in enumerate(zip(distances, levels))]}


class RouteSummaryTests(SimpleTestCase):
    def test_numeric_scale(self):
        self.assertEqual(RISK_SCALE, {"Low": 0, "Moderate": 1, "High": 2, "Severe": 3, "No Travel": 4})

    def test_67_mile_route_final_segment_is_17_miles(self):
        value = fixture("final", [0, 25, 50, 67], ["Low", "Low", "Low", "Severe"])
        original = deepcopy(value)
        summary, segments = summarize_route(value)
        self.assertAlmostEqual(segments[-1]["distance_miles"], 17, places=12)
        self.assertAlmostEqual(summary["severe_miles"], 17, places=12)
        self.assertAlmostEqual(summary["distance_miles"], 67, places=12)
        self.assertAlmostEqual(summary["average_risk"], 51 / 67)
        self.assertEqual(value, original)

    def test_segment_uses_higher_endpoint_in_both_directions(self):
        summary, segments = summarize_route(fixture("mixed", [0, 10, 35, 50], ["Low", "High", "Severe", "Moderate"]))
        self.assertEqual([s["risk_level"] for s in segments], ["High", "Severe", "Severe"])
        self.assertAlmostEqual(summary["high_miles"], 10)
        self.assertAlmostEqual(summary["severe_miles"], 40)
        self.assertAlmostEqual(summary["average_risk"], 2.8)

    def test_partial_rating_is_unknown_and_excluded(self):
        summary, segments = summarize_route(fixture("partial", [0, 25, 50], ["Low", "High", "Low"], incomplete=(1,)))
        self.assertEqual([s["risk_level"] for s in segments], ["Unknown", "Unknown"])
        self.assertEqual(summary["unknown_coverage_miles"], 50)
        self.assertEqual(summary["unknown_risk_miles"], 50)
        self.assertIsNone(summary["average_risk"])
        self.assertFalse(summary["eligible"])

    def test_no_travel_survives_incomplete_other_endpoint(self):
        summary, segments = summarize_route(fixture("blocked", [0, 17], ["No Travel", "Unknown"]))
        self.assertEqual(segments[0]["risk_level"], "No Travel")
        self.assertEqual(summary["no_travel_miles"], 17)
        self.assertEqual(summary["unknown_coverage_miles"], 17)
        self.assertEqual(summary["unknown_risk_miles"], 0)
        self.assertEqual(summary["average_risk"], 4)
        self.assertEqual({r["code"] for r in summary["exclusion_reasons"]}, {"no_travel_segments", "incomplete_forecast_coverage"})

    def test_partial_no_travel_itself_is_preserved(self):
        summary, _ = summarize_route(fixture("blocked", [0, 25], ["No Travel", "Low"], incomplete=(0,)))
        self.assertEqual(summary["no_travel_miles"], 25)
        self.assertFalse(summary["forecast_coverage_complete"])

    def test_exact_multiple_has_no_extra_segment(self):
        summary, segments = summarize_route(fixture("multiple", [0, 25, 50], ["High", "High", "High"]))
        self.assertEqual(len(segments), 2)
        self.assertEqual(summary["high_miles"], 50)

    def test_uses_unrounded_checkpoint_distances(self):
        value = fixture("precise", [0, 25, 25.0000004], ["Low", "Low", "High"])
        summary, _ = summarize_route(value)
        self.assertGreater(summary["high_miles"], 0)
        self.assertAlmostEqual(summary["high_miles"], .0000004, places=12)


class RankingTests(SimpleTestCase):
    def test_longer_route_with_fewer_severe_miles_wins(self):
        routes = [fixture("short", [0, 25, 50], ["Severe", "Low", "Low"], 1800),
                  fixture("long", [0, 25, 50, 67], ["Low", "Low", "Low", "Severe"], 7200)]
        result = summarize_and_recommend(routes)
        self.assertEqual(result["recommended_route_id"], "long")
        self.assertEqual(result["deciding_factor"], "severe_miles")

    def test_high_miles_break_severe_tie(self):
        routes = [fixture("high25", [0, 25, 50], ["High", "Low", "Low"], 1800),
                  fixture("high17", [0, 25, 50, 67], ["Low", "Low", "Low", "High"], 7200)]
        result = summarize_and_recommend(routes)
        self.assertEqual(result["recommended_route_id"], "high17")
        self.assertEqual(result["deciding_factor"], "high_miles")

    def test_average_breaks_severe_and_high_tie(self):
        routes = [fixture("moderate", [0, 50], ["Moderate", "Moderate"], 1800),
                  fixture("low", [0, 67], ["Low", "Low"], 7200)]
        result = summarize_and_recommend(routes)
        self.assertEqual(result["recommended_route_id"], "low")
        self.assertEqual(result["deciding_factor"], "average_risk")

    def test_travel_time_is_final_tiebreaker(self):
        routes = [fixture("slow", [0, 50], ["Moderate", "Moderate"], 7200),
                  fixture("fast", [0, 67], ["Moderate", "Moderate"], 1800)]
        result = summarize_and_recommend(routes)
        self.assertEqual(result["recommended_route_id"], "fast")
        self.assertEqual(result["deciding_factor"], "duration_seconds")

    def test_each_priority_dominates_conflicting_later_criteria(self):
        # Fewer Severe miles wins even with more High miles and a worse average/time.
        routes = [fixture("severe", [0, 1, 100], ["Severe", "Low", "Low"], 100),
                  fixture("high", [0, 100], ["High", "High"], 10000)]
        self.assertEqual(summarize_and_recommend(routes)["recommended_route_id"], "high")
        # Fewer High miles wins even with a worse average/time.
        routes = [fixture("high", [0, 1, 100], ["High", "Low", "Low"], 100),
                  fixture("moderate", [0, 100], ["Moderate", "Moderate"], 10000)]
        self.assertEqual(summarize_and_recommend(routes)["recommended_route_id"], "moderate")

    def test_ranking_uses_raw_values_that_round_to_same_display(self):
        routes = [fixture("larger", [0, 25.004], ["Severe", "Severe"], 100),
                  fixture("smaller", [0, 25.003], ["Severe", "Severe"], 10000)]
        result = summarize_and_recommend(routes)
        self.assertEqual(routes[0]["summary"]["display"]["severe_miles"], routes[1]["summary"]["display"]["severe_miles"])
        self.assertEqual(result["recommended_route_id"], "smaller")
        self.assertEqual(result["deciding_factor"], "severe_miles")

    def test_unrounded_average_and_time_comparisons(self):
        routes = [fixture("larger", [0, 1.004, 100], ["Moderate", "Low", "Low"], 100),
                  fixture("smaller", [0, 1.003, 100], ["Moderate", "Low", "Low"], 10000)]
        self.assertEqual(summarize_and_recommend(routes)["recommended_route_id"], "smaller")
        self.assertEqual(routes[0]["summary"]["display"]["average_risk"], routes[1]["summary"]["display"]["average_risk"])
        routes = [fixture("slower", [0, 1], ["Low", "Low"], 100.004), fixture("faster", [0, 1], ["Low", "Low"], 100.003)]
        self.assertEqual(summarize_and_recommend(routes)["recommended_route_id"], "faster")

    def test_excluded_routes_never_win(self):
        routes = [fixture("no-travel", [0, 1], ["No Travel", "Low"], 10),
                  fixture("missing", [0, 1], ["Low", "Unknown"], 10),
                  fixture("eligible", [0, 50], ["Severe", "Severe"], 10000)]
        result = summarize_and_recommend(routes)
        self.assertEqual(result["recommended_route_id"], "eligible")
        self.assertEqual(result["deciding_factor"], "only_eligible_route")

    def test_all_excluded_and_empty_routes(self):
        for routes in ([], [fixture("blocked", [0, 1], ["No Travel", "Unknown"])]):
            result = summarize_and_recommend(routes)
            self.assertEqual(result["status"], "no_recommendation")
            self.assertIsNone(result["recommended_route_id"])

    def test_exact_ties_keep_provider_order(self):
        routes = [fixture("first", [0, 50], ["Low", "Low"]), fixture("second", [0, 50], ["Low", "Low"])]
        result = summarize_and_recommend(routes)
        self.assertEqual(result["recommended_route_id"], "first")
        self.assertEqual(result["deciding_factor"], "exact_tie")


@override_settings(ALLOWED_HOSTS=["testserver"])
class RankingAPITests(SimpleTestCase):
    @patch("api.weather.requests.get")
    @patch("api.views.fetch_trip")
    def test_all_excluded_returns_200_with_reasons_and_null_recommendation(self, trip, get):
        trip.return_value = ([{}, {}], [here_route(3, duration=7200)])
        data = forecast()
        data["hourly"]["rain"][2] = None
        get.return_value.json.return_value = [data, data]
        response = APIClient().post("/api/trips/analyze", {"origin": "A", "destination": "B", "departure_time": "2026-11-25T08:00:00Z", "load_weight_lbs": 100}, format="json")
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertIsNone(result["recommended_route_id"])
        self.assertEqual(result["recommendation"]["status"], "no_recommendation")
        summary = result["routes"][0]["summary"]
        self.assertGreater(summary["no_travel_miles"], 0)
        self.assertGreater(summary["unknown_coverage_miles"], 0)
        self.assertEqual(len(summary["exclusion_reasons"]), 2)

    @patch("api.weather.requests.get")
    @patch("api.views.fetch_trip")
    def test_eligible_route_has_recommendation_through_real_pipeline(self, trip, get):
        trip.return_value = ([{}, {}], [here_route(3, duration=600)])
        get.return_value.json.return_value = [forecast(), forecast()]
        response = APIClient().post("/api/trips/analyze", {"origin": "A", "destination": "B", "departure_time": "2026-11-25T08:00:00Z", "load_weight_lbs": 100}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["recommended_route_id"], "primary")
        self.assertEqual(response.json()["recommendation"]["status"], "recommended")
