# Phase 3 — checkpoint weather and risk

## Scope and verification commands

`POST /api/trips/analyze` now enriches every route checkpoint with hourly
Open-Meteo weather selected using that checkpoint's ETA, plus a pure risk
classification. Routing, cargo semantics and checkpoint spacing from Phase 2
are retained. No route ranking, weather map or frontend workflow is added.

From the repository root, using the existing environment:

```powershell
./.venv/Scripts/python.exe backend/manage.py test api.test_weather -v 2
./.venv/Scripts/python.exe backend/manage.py test api -v 2
./.venv/Scripts/python.exe backend/manage.py check
```

Phase 1 regressions, from `backend/`:

```powershell
../.venv/Scripts/python.exe -m unittest test_providers -v
```

No additional dependencies or credentials are needed for the automated tests.
Weather tests mock HTTP forecast responses; API integration tests mock HERE
routes and weather HTTP only, exercising the actual selection/conversion/risk
pipeline. Phase 2 route tests isolate weather enrichment to remain offline.

## Forecast request and ETA mapping

The backend requests `wind_speed_10m,rain,snowfall`, `wind_speed_unit=kmh`,
`precipitation_unit=mm`, `timeformat=iso8601`, `timezone=UTC`, and
`forecast_days=16` from `https://api.open-meteo.com/v1/forecast`.
Open-Meteo provides instantaneous hourly wind and preceding-hour precipitation
totals. Metric output is wind in km/h, rain in mm and snowfall depth in cm.
The rain field excludes convective showers; it is not total precipitation or
snow water equivalent. See the [provider field documentation](https://open-meteo.com/en/docs).

Our selection policy is explicit and deterministic:

- Convert the checkpoint ETA to UTC. Offsetless provider timestamps are interpreted
  as UTC only with the requested UTC response (`utc_offset_seconds=0`). Offset-aware
  timestamps are converted to UTC. Unexpected response offsets are flagged unavailable.
- **Wind:** choose the nearest hourly instantaneous reading. At exactly 30 minutes,
  choose the later hour. No interpolation or smoothing is performed.
- **Rain and snow:** choose the hourly total whose interval `(timestamp − 1 hour,
  timestamp]` contains the ETA. At 09:10 use the 10:00 total for 09:00–10:00;
  at exactly 09:00 use the 09:00 total for 08:00–09:00. Divide the one-hour total
  by one hour, so the numerical amount becomes the hourly average rate. This is
  an hourly rate estimate, not a measured instantaneous precipitation intensity.
- `forecast_timestamp` is the selected precipitation interval-end timestamp,
  or null if that row is absent. `field_timestamps` records the actual selected
  timestamp for each field; wind can use a different hour. A timestamp can exist
  even if its value is null; always inspect coverage and normalized values.
- Never select the departure hour for every checkpoint, clamp outside coverage,
  substitute zero for missing values, or reuse a nearby hour to fill a gap.
  ETAs before the first or after the last returned timestamp are unavailable.

At ETA `2026-11-25T10:10:00+01:00` (09:10 UTC), wind uses 09:00 UTC,
while rain/snow use 10:00 UTC. A departure at 08:00 UTC has no influence on
this selection. At 09:30 UTC, all three use the 10:00 row.

## Unit conversion before classification

`api/weather.py` checks each field's returned unit independently:

| Provider field | Normalized field | Calculation |
| --- | --- | --- |
| `wind_speed_10m`, km/h | `wind_mph` | km/h ÷ 1.609344 |
| `rain`, mm in one hour | `rain_in_per_hour` | mm ÷ 25.4 ÷ 1 hour |
| `snowfall`, cm in one hour | `snow_in_per_hour` | cm ÷ 2.54 ÷ 1 hour |

Decimal arithmetic is used during conversion before returning numeric floats.
Classification uses the converted values without display rounding. Unknown or
missing units make only that field unavailable. Null, absent, short-array,
negative, nonnumeric, boolean or nonfinite readings are missing, never zero.

## Pure classifier and coverage

`api/risk.py::classify_risk(wind_mph, rain_in_per_hour, snow_in_per_hour,
load_weight_lbs)` has no HTTP calls, settings, clock, file access or mutation.
Cargo weight must be finite and positive. It returns the highest observed risk,
all tied triggering conditions and reasons, missing fields, coverage completeness
and assessment status. Load override comparisons are strictly greater than.

| Condition | Low | Moderate | High | Severe | No Travel |
| --- | --- | --- | --- | --- | --- |
| Wind mph | <25 | 25–<35 | 35–<45 | 45–<55 | ≥55 |
| Rain in/hr | <0.10 | 0.10–<0.25 | 0.25–<0.50 | 0.50–1.00 inclusive | >1.00 |
| Snow in/hr | <0.5 | 0.5–<1.0 | 1.0–<2.0 | 2.0–3.0 inclusive | >3.0 |

- Wind 45–<55 mph and cargo **>30,000 lb** → No Travel.
- Wind 35–<45 mph and cargo **>40,000 lb** → Severe.
- Wind ≥55 mph → No Travel for every valid load.

Incomplete data does not erase evidence. If wind is 55 mph but rain is missing,
the result remains No Travel, `assessment_status=confirmed`, and
`coverage_complete=false`. Any confirmed rain, snow or load-override No Travel
is preserved too. With some data but no No Travel, the label is the highest
**known** risk and `assessment_status=incomplete`: a Low label in this state is
not a complete Low assessment. With no usable fields, the level is Unknown.
Complete coverage yields `assessment_status=confirmed`; this describes evaluation
of the assessment rules, not a guarantee about actual future driving conditions.

## Response additions and failure behavior

The existing route response is retained. Every checkpoint adds:

```json
{
  "weather": {
    "provider": "open-meteo",
    "forecast_timestamp": "2026-11-25T10:00:00Z",
    "field_timestamps": {
      "wind_mph": "2026-11-25T10:00:00Z",
      "rain_in_per_hour": "2026-11-25T10:00:00Z",
      "snow_in_per_hour": "2026-11-25T10:00:00Z"
    },
    "values": {"wind_mph": 55.0, "rain_in_per_hour": null, "snow_in_per_hour": 3.0},
    "coverage": {
      "status": "partial",
      "missing_fields": ["rain_in_per_hour"],
      "issues": {"rain_in_per_hour": "missing_or_invalid_value"}
    },
    "requested_coordinates": {"latitude": 50.11208, "longitude": 8.68341}
  },
  "risk": {
    "level": "No Travel",
    "reasons": ["Wind 55 mph: No Travel."],
    "triggering_conditions": ["wind_mph"],
    "coverage_complete": false,
    "missing_fields": ["rain_in_per_hour"],
    "assessment_status": "confirmed"
  }
}
```

Top-level `weather_coverage` counts complete, partial and unavailable checkpoint
assessments across all routes. It counts checkpoints, not unique coordinates.

Weather HTTP errors, timeouts, malformed JSON, missing rows, unsupported units
and out-of-range ETAs produce explicit coverage issues. The routing response
remains HTTP 200 with available routes and partial/Unknown assessments. HERE
failures still use the Phase 2 errors. Weather failure never implies Low risk.
Each HTTP weather request has a 30-second timeout. No raw provider error body
is exposed.

## Request reuse

Coordinates are rounded to five decimal places (roughly metre-scale) and
deduplicated across all checkpoints and alternatives within one analysis.
Up to 50 unique coordinates are requested together using Open-Meteo's ordered
multi-location response. A single-coordinate object response is also accepted.
Each location's hourly series is then independently selected for each checkpoint
ETA, including when two alternatives reach the same coordinate at different times.
The original checkpoint/map coordinates are unchanged; `requested_coordinates`
shows the forecast lookup position. There is no persistent forecast cache.

A response-count mismatch invalidates that batch to avoid assigning the wrong
location's weather. Other batches can still succeed. Missing data at one location
does not invalidate another location's valid fields.

## Repeatable input / expected-result table

Unless stated otherwise, other weather fields are zero and cargo is 100 lb.
The tests in `api/test_weather.py` use synthetic forecasts and these exact rules.

| Input | Expected result |
| --- | --- |
| Wind 24.999 / 25 mph | Low / Moderate |
| Wind 34.999 / 35 mph | Moderate / High |
| Wind 44.999 / 45 mph | High / Severe |
| Wind 54.999 / 55 mph | Severe / No Travel |
| Rain 0.09999 / 0.10 in/hr | Low / Moderate |
| Rain 0.24999 / 0.25 in/hr | Moderate / High |
| Rain 0.49999 / 0.50 in/hr | High / Severe |
| Rain 1.00 / 1.00001 in/hr | Severe / No Travel |
| Snow 0.49999 / 0.50 in/hr | Low / Moderate |
| Snow 0.99999 / 1.00 in/hr | Moderate / High |
| Snow 1.99999 / 2.00 in/hr | High / Severe |
| Snow 3.00 / 3.00001 in/hr | Severe / No Travel |
| Wind 45 mph, cargo 30,000 / 30,000.01 lb | Severe / No Travel |
| Wind 35 mph, cargo 40,000 / 40,000.01 lb | High / Severe |
| Wind 34.999 mph, cargo 50,000 lb | Moderate; no load override |
| Wind 55 mph, cargo 1 or 50,000 lb | No Travel for both |
| Wind 25 mph, rain 0.5, snow 3 in/hr | Severe; both rain and snow listed as reasons |
| 40.2336 km/h, 2.54 mm, 1.27 cm | 25 mph, 0.1 in/hr rain, 0.5 in/hr snow; Moderate |
| 88.51392 km/h, 25.4 mm, 7.62 cm | 55 mph, 1 in/hr rain, 3 in/hr snow; No Travel from wind |
| Departure 08:00Z, checkpoint ETA 11:00+01:00 | Select 10:00Z, not 08:00Z |
| ETA 09:10Z | Wind 09:00Z; precipitation interval ends 10:00Z |
| ETA 09:30Z | Wind 10:00Z (tie later); precipitation 10:00Z |
| ETA exactly 09:00Z | All selected timestamps 09:00Z |
| ETA 00:45+01:00 across UTC midnight | Precipitation ends 00:00Z, for 23:00–00:00 UTC |
| Wind 55 mph, missing rain | No Travel confirmed; partial coverage |
| Missing wind, rain 1.01 in/hr | No Travel confirmed; incomplete coverage |
| Wind 45 mph, cargo 30,001 lb, rain/snow missing | No Travel confirmed; incomplete coverage |
| Wind/rain 0, snow missing | Known Low; assessment incomplete |
| All fields missing or weather provider times out | Unknown; unavailable coverage |
| ETA 07:59:59Z or 11:00:01Z with series covering 08:00–11:00Z | Unknown; `eta_out_of_forecast_range` |
| Snowfall unit unexpectedly mm | Snow unavailable; other valid fields still classified |

The API-level mock has a 2-hour route departing 08:00Z with calm departure
weather and 55 mph destination wind at 10:00Z. Its destination rain is null.
Expected HTTP 200: origin Low/complete, destination No Travel/partial, and
`weather_coverage={complete:1, partial:1, unavailable:0}`.

## Manual API walkthrough and optional live check

1. Set a valid backend `HERE_API_KEY`; Open-Meteo requires no key for this check.
   Restart Django to load environment changes:

   ```powershell
   ./.venv/Scripts/python.exe backend/manage.py runserver 127.0.0.1:8000
   ```

2. In a second terminal at the root, create a dated request in the gitignored
   results directory. This uses tomorrow at 09:00 UTC, inside the forecast window:

   ```powershell
   New-Item -ItemType Directory -Force docs/testing/results | Out-Null
   $tripDeparture = [DateTime]::UtcNow.Date.AddDays(1).AddHours(9).ToString("yyyy-MM-ddTHH:mm:ssZ")
   @{ origin = "Frankfurt am Main, Germany"; destination = "Kassel, Germany"; departure_time = $tripDeparture; load_weight_lbs = 12000; checkpoint_interval_miles = 25 } | ConvertTo-Json | Set-Content -Encoding ascii docs/testing/results/phase-03-request.json
   curl.exe -sS -X POST http://127.0.0.1:8000/api/trips/analyze -H "Content-Type: application/json" --data-binary "@docs/testing/results/phase-03-request.json" -o docs/testing/results/phase-03-response.json
   ```

   In Postman, use the same POST URL, raw JSON body and generated request file.
   Existing Phase 2 requests also work; change expired dates before live testing.

3. Inspect a compact summary instead of printing thousands of map coordinates:

   ```powershell
   $tripResult = Get-Content docs/testing/results/phase-03-response.json -Raw | ConvertFrom-Json
   $tripResult.weather_coverage
   $tripResult.routes | ForEach-Object { $_.checkpoints | Select-Object distance_miles, eta, @{Name="Risk";Expression={$_.risk.level}}, @{Name="Coverage";Expression={$_.weather.coverage.status}}, @{Name="Forecast";Expression={$_.weather.forecast_timestamp}} }
   ```

4. Inspect `weather.values`, `field_timestamps`, and `risk.reasons` on a later
   checkpoint. Confirm selection follows ETA, all timestamps are UTC, and final
   checkpoints retain their Phase 2 destination ETA. Compare results for load
   values only when wind is in an override range. Calm live weather will not
   exercise overrides; use the mocked boundary tests instead.
5. For deterministic missing/out-of-range cases use the test command above.
   A very distant live trip date may be rejected by HERE before weather lookup,
   so it is not a reliable way to test weather coverage handling.

## Execution record — 24 November 2026

- All Django API tests: **47 passed** (23 Phase 3 tests, 24 existing tests).
- Phase 1 provider regressions: **3 passed**. Django system check: **passed**.
- Live analysis through the Django view with actual HERE/Open-Meteo HTTP calls:
  **HTTP 200** for Frankfurt am Main → Kassel, departure
  **2026-11-25T09:00:00+00:00**, cargo 12,000 lb, interval 25 miles.
- Returned **3 distinct routes**, 6 checkpoints per route: **18 complete**, 0
  partial, 0 unavailable. All 18 risk classifications were Low for that forecast.
- First checkpoint: wind approximately **4.59815 mph**, rain **0 in/hr**, snow
  **0 in/hr**; selected timestamp **2026-11-25T09:00:00Z**.
- Sanitized request and full response saved locally to
  `docs/testing/results/phase-03-live.json` (gitignored). Forecasts, traffic and
  route IDs can change; this is evidence of that run, not a fixed live fixture.

Stopped after Phase 3.
