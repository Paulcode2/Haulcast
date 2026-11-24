# Phase 4 — route summaries and recommendation

## Scope and test commands

`POST /api/trips/analyze` now returns each route's segment classifications,
distance-weighted summary, recommendation eligibility and exclusion reasons.
The top-level response includes `recommended_route_id` and `recommendation`.
The existing route, checkpoint, forecast and risk fields remain available.
No frontend or later-phase features are added.

From the repository root, using the existing environment:

```powershell
./.venv/Scripts/python.exe backend/manage.py test api.test_ranking -v 2
./.venv/Scripts/python.exe backend/manage.py test api -v 2
./.venv/Scripts/python.exe -m unittest discover -s backend -p test_providers.py -v
./.venv/Scripts/python.exe backend/manage.py check
```

All automated tests are deterministic and offline. API ranking tests mock HERE
and Open-Meteo HTTP responses while exercising the real normalization, weather
selection, risk, summary and recommendation code.

## Segment classification and distance

For each consecutive pair of checkpoints:

1. Segment length is `(end.distance_meters − start.distance_meters) / 1609.344`.
   `distance_meters` is a new **unrounded cumulative geometry-distance** field
   on each checkpoint. The older rounded `distance_miles` field is retained for
   compatibility and is never used for ranking calculations.
2. If both checkpoints have complete forecasts and known ratings, use the higher
   rating. For example Low → High and High → Low both make a High segment.
3. If either endpoint has confirmed No Travel, retain No Travel even if the other
   endpoint is Unknown or either endpoint has incomplete weather coverage.
4. Otherwise incomplete coverage makes the segment Unknown. A partial checkpoint's
   highest observed rating is not a fully known rating: missing weather could
   raise it. Both the risk completeness flag and weather coverage status must
   indicate complete coverage.

Distances follow the decoded polyline, not a straight line between checkpoints,
the nominal interval, or HERE's separately reported road-network length. Summed
segment miles equal the checkpoint-covered geometry length. Floating-point
arithmetic has ordinary machine-precision error; tests allow that precision,
never a whole-mile approximation.

## Summary and risk scale

The consistent numeric scale is:

| Rating | Score |
| --- | --- |
| Low | 0 |
| Moderate | 1 |
| High | 2 |
| Severe | 3 |
| No Travel | 4 |
| Unknown | No numeric score |

`average_risk = sum(segment_miles × segment_score) / sum(segment_miles)`.
If any segment has Unknown risk, `average_risk` is null rather than treating
unknown miles as zero or dropping them from the denominator. If every segment
is known No Travel despite some missing weather, the average can be 4 while
coverage remains incomplete; this route is still excluded.

Each route's `summary` contains:

| Field | Meaning |
| --- | --- |
| `distance_miles` | Actual checkpoint-covered geometry miles |
| `severe_miles` | Miles classified exactly Severe |
| `high_miles` | Miles classified exactly High |
| `no_travel_miles` | Miles classified No Travel |
| `unknown_coverage_miles` | Miles adjoining at least one checkpoint with incomplete coverage |
| `unknown_risk_miles` | Miles that cannot receive a final risk rating |
| `average_risk` | Distance-weighted score, or null if any segment risk is unknown |
| `forecast_coverage_complete` | Every checkpoint has complete forecast coverage and a known rating |
| `eligible` | No exclusion reasons apply |
| `exclusion_reasons` | List of code/message pairs; empty for eligible routes |
| `display` | Numeric summary fields rounded to two decimal places for presentation |

Severe, High and No Travel are separate categories, not cumulative thresholds.
Unknown coverage is a separate dimension: **No Travel miles and unknown coverage
miles may overlap**. For example, a 17-mile segment from No Travel to Unknown
contributes 17 No Travel miles and 17 unknown coverage miles, but zero unknown
risk miles. Do not add these overlapping coverage and risk counts together as
if they partitioned the route.

Each route also has `segments`, containing checkpoint indexes, unrounded
`distance_miles`, `risk_level`, and `forecast_coverage_complete`.

## Eligibility and exact comparison order

Routes are excluded if either applies (both reasons are returned when applicable):

- `no_travel_segments`: one or more segments are No Travel.
- `incomplete_forecast_coverage`: one or more checkpoints lack full coverage.

Eligible routes are compared lexicographically in **exactly** this order:

1. Fewest Severe miles.
2. Fewest High miles.
3. Lowest distance-weighted average risk.
4. Shortest `duration_seconds`.

All comparisons use the original unrounded floats, not `summary.display`, rounded
checkpoint miles, or an epsilon tie. Route length is not an additional criterion.
On an exact tie of all four values, preserve provider order and explicitly report
`deciding_factor=exact_tie`; this is stable tie handling, not a fifth optimization
criterion. The returned route array stays in provider order.

The explanation names the first differing criterion between the winner and the
next-ranked eligible route. This wording also covers three or more routes where
different competitors may lose at different criteria. If only one route is
eligible, `deciding_factor=only_eligible_route`.

If all routes are excluded, the API returns HTTP 200 with all routes and reasons,
`recommended_route_id=null`, `recommendation.status=no_recommendation`, and a
clear explanation. There is no fallback to an unsafe or incompletely assessed
route. HERE returning no routes remains the existing Phase 2 HTTP 422 case.

## Fixtures that independently exercise each tie-breaker

`api/test_ranking.py::fixture` builds checkpoints using exact input mile positions
converted to metres. Unless noted, coverage is complete. The following fixtures
are implemented as tests, not just illustrative expected values.

| Deciding criterion | Route A | Route B | Expected winner |
| --- | --- | --- | --- |
| Severe miles | 50 mi, checkpoints 0/25/50 rated Severe/Low/Low; 25 Severe mi; 1,800 s | 67 mi, 0/25/50/67 rated Low/Low/Low/Severe; 17 Severe mi; 7,200 s | B, despite being longer and slower |
| High miles | 50 mi, 0/25/50 rated High/Low/Low; 0 Severe, 25 High mi; 1,800 s | 67 mi, 0/25/50/67 rated Low/Low/Low/High; 0 Severe, 17 High mi; 7,200 s | B; Severe miles tie |
| Average risk | 50 mi entirely Moderate; 0 Severe/High, average 1; 1,800 s | 67 mi entirely Low; 0 Severe/High, average 0; 7,200 s | B; Severe and High miles tie |
| Travel time | 50 mi entirely Moderate; average 1; 7,200 s | 67 mi entirely Moderate; average 1; 1,800 s | B; all risk metrics tie |

Additional priority-conflict fixtures verify that:

- Zero Severe miles with 100 High miles wins over 1 Severe mile plus 99 Low
  miles, even though the winning route has a worse average and travel time.
- Zero High miles with 100 Moderate miles wins over 1 High mile plus 99 Low
  miles, even though the winning route has a worse average and travel time.
- 25.003 Severe miles beats 25.004 even though both display as 25.00.
- Unrounded averages and travel times also break ties hidden by display rounding.
- A fast No Travel route and a fast incomplete route are excluded even when a
  much slower eligible route is Severe throughout.

### Verify the shorter final segment

Run just the deterministic final-segment fixture:

```powershell
./.venv/Scripts/python.exe backend/manage.py test api.test_ranking.RouteSummaryTests.test_67_mile_route_final_segment_is_17_miles -v 2
```

Checkpoints at **0, 25, 50, 67 miles**, rated **Low, Low, Low, Severe**, produce:

| Segment | Length | Rating | Weighted contribution |
| --- | --- | --- | --- |
| 0 → 25 | 25 mi | Low | 25 × 0 = 0 |
| 25 → 50 | 25 mi | Low | 25 × 0 = 0 |
| 50 → 67 | **17 mi** | Severe | **17 × 3 = 51** |

Total length is 67, Severe miles are 17, and average risk is **51 / 67**, about
0.761194. It is not 25 Severe miles, an unweighted mean of checkpoint ratings,
or an unweighted mean of segment ratings. Exact-multiple fixtures also verify
that 0/25/50 produces only two segments and no phantom endpoint segment.

## Sample successful response

This is a focused excerpt from the two-route Severe-mile fixture. Existing
geometry, checkpoints, weather and other summary fields are omitted here for
readability; the API still returns them.

```json
{
  "recommended_route_id": "long",
  "recommendation": {
    "recommended_route_id": "long",
    "status": "recommended",
    "deciding_factor": "severe_miles",
    "explanation": "Fewest Severe miles decides the comparison with the next-ranked eligible route."
  },
  "routes": [
    {
      "id": "short",
      "duration_seconds": 1800,
      "summary": {
        "distance_miles": 50,
        "severe_miles": 25,
        "high_miles": 0,
        "no_travel_miles": 0,
        "unknown_coverage_miles": 0,
        "average_risk": 1.5,
        "eligible": true,
        "exclusion_reasons": []
      }
    },
    {
      "id": "long",
      "duration_seconds": 7200,
      "summary": {
        "distance_miles": 67,
        "severe_miles": 17,
        "high_miles": 0,
        "no_travel_miles": 0,
        "unknown_coverage_miles": 0,
        "average_risk": 0.7611940298507462,
        "eligible": true,
        "exclusion_reasons": []
      }
    }
  ]
}
```

## All routes excluded: endpoint verification

```powershell
./.venv/Scripts/python.exe backend/manage.py test api.test_ranking.RankingAPITests.test_all_excluded_returns_200_with_reasons_and_null_recommendation -v 2
```

The mocked route starts at 08:00Z and reaches its destination at 10:00Z. At the
destination wind is 55 mph, while rain is missing. The real weather classifier
retains No Travel and partial coverage. The segment summary preserves both
findings, and the endpoint returns HTTP 200 with this recommendation:

```json
{
  "recommended_route_id": null,
  "recommendation": {
    "recommended_route_id": null,
    "status": "no_recommendation",
    "deciding_factor": null,
    "explanation": "No route has both complete forecast coverage and no No Travel segments."
  }
}
```

The route's `summary.exclusion_reasons` includes both
`no_travel_segments` and `incomplete_forecast_coverage`. Other tests cover
incomplete-only exclusion, known No Travel beside Unknown, a single eligible
route and exact ties.

## Manual request

Use the Phase 3 request workflow to select tomorrow within the forecast horizon,
then POST the same request (no new input fields):

```powershell
curl.exe -sS -X POST http://127.0.0.1:8000/api/trips/analyze -H "Content-Type: application/json" --data-binary "@docs/testing/results/phase-03-request.json" -o docs/testing/results/phase-04-response.json
$tripResult = Get-Content docs/testing/results/phase-04-response.json -Raw | ConvertFrom-Json
$tripResult.recommendation
$tripResult.routes | ForEach-Object { [PSCustomObject]@{ ID=$_.id; Severe=$_.summary.severe_miles; High=$_.summary.high_miles; Average=$_.summary.average_risk; Seconds=$_.duration_seconds; Eligible=$_.summary.eligible; Exclusions=$_.summary.exclusion_reasons.code } }
```

Compare eligible routes by the four raw columns in order. Check that the winner
ID is present and eligible. Use fixtures for adverse weather and exact ties;
live weather cannot reliably reproduce those cases.

## Execution record — 24 November 2026

- Ranking tests: **20 passed**.
- Full Django API suite: **67 passed**, including all 47 earlier tests.
- Phase 1 provider regressions: **3 passed**.
- Django system check: **passed**, no issues.
- Endpoint tests cover both a recommendation and HTTP 200 with no recommendation
  when every route is excluded. No live third-party calls are needed for ranking.

Stopped after Phase 4.
