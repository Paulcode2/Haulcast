import unittest
from unittest.mock import patch

import flexpolyline
import requests

from check_providers import CheckError, check_here, get_json, route_summary


def section(points, length=100, duration=10):
    return {"polyline": flexpolyline.encode(points), "summary": {"length": length, "duration": duration}}


class ProviderContractTests(unittest.TestCase):
    def test_all_sections_are_counted_and_shared_endpoints_normalized(self):
        a, b, c = (50.0, 8.0), (50.1, 8.1), (50.2, 8.2)
        split = route_summary({"id": "split", "sections": [section([a, b]), section([b, c])]})
        whole = route_summary({"id": "whole", "sections": [section([a, b, c], 200, 20)]})
        self.assertEqual(split["distance_m"], 200)
        self.assertEqual(split["duration_s"], 20)
        self.assertEqual(split["geometry_points"], 3)
        self.assertEqual(split["geometry_sha256"], whole["geometry_sha256"])

    @patch("check_providers.get_json")
    @patch("check_providers.geocode")
    def test_different_ids_with_duplicate_geometry_do_not_pass(self, geocode, get):
        geocode.return_value = {"routing_position": {"lat": 50, "lng": 8}}
        get.return_value = {"routes": [{"id": str(i), "sections": [section([(50, 8), (51, 9)])]} for i in range(3)]}
        result = check_here("a", "b", "2026-11-25T09:00:00+01:00", "test-key")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["distinct_geometry_count"], 1)
        self.assertNotIn("apiKey", result["request"])

    @patch("check_providers.requests.get")
    def test_http_errors_do_not_expose_query_credentials(self, get):
        response = requests.Response()
        response.status_code = 401
        get.return_value.raise_for_status.side_effect = requests.HTTPError("https://example.com?apiKey=SECRET", response=response)
        with self.assertRaises(CheckError) as caught:
            get_json("https://example.com", {"apiKey": "SECRET"})
        self.assertIn("401", str(caught.exception))
        self.assertNotIn("SECRET", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
