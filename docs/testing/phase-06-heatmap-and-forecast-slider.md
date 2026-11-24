# Phase 6 — corridor heatmap and forecast slider

## Scope

`POST /api/trips/analyze` now returns `corridor_forecast`: sampled points along
and around every returned route with hourly weather for hours 0–48 from an
explicit reference timestamp. React renders those points as a heatmap layer and
adds a 0–48 forecast slider. Scrubbing updates only the heatmap from
already-loaded data: no new forecast requests, and route geometry, selection,
checkpoint ETAs and the recommendation stay unchanged. Stale heatmap data is
replaced when a new trip loads. No ranking, routing or checkpoint-ETA logic
changed.

## Backend: sampling, batching, reference time

`backend/api/corridor.py`:

- `forecast_reference_time(departure)` floors the departure to the UTC hour.
  Hour 0 is that timestamp; hour 48 is reference + 48 h. The response carries
  `forecast_reference_time`, `timezone: "UTC"`, `hour_count: 49` and all 49
  `timestamps`.
- `sample_corridor_points(routes)` walks each route geometry every 5 miles and
  adds lateral offsets of 0 and ±6 miles (perpendicular to travel direction),
  so the heatmap covers the corridor, not just the centerline. Samples are
  deduplicated at 4-decimal precision (~11 m) and bounded to 250 points;
  overflow sets `truncated: true` with deterministic stride thinning.
- `build_corridor_forecast(routes, departure, load_weight_lbs)` reuses the
  existing `fetch_forecasts` batching (50 unique coordinates per Open-Meteo
  request, ordered multi-location responses). Each point carries 49-entry
  arrays: `wind_mph`, `rain_in_per_hour`, `snow_in_per_hour`, `risk_levels`
  (Low/Moderate/High/Severe/No Travel or `"Unavailable"`) and `intensities`
  (risk score ÷ 4, or `null`). Missing hours, unit mismatches, invalid values
  and provider errors are explicit `Unavailable`/`null` — never zero, never
  clamped, never carried from a nearby hour.
- `views.analyze_trip` attaches `corridor_forecast` alongside the unchanged
  `routes`, `recommendation` and `weather_coverage` fields.

## Frontend: slider, layer, legend

- `TripMap.jsx` adds a `corridor-heat` circle layer fed from
  `corridor.points[forecastHour]`. Color maps intensity 0 → Low green through
  0.5 → High orange to 1 → No Travel purple; `null` renders gray
  (`#9aa7b2`) for unavailable hours.
- The slider (`min 0, max 48, step 1`) label shows the selected hour plus its
  exact UTC timestamp; the status line shows available/total points and the
  hour-0 reference with timezone, e.g.
  `3 of 3 corridor points have a forecast at hour 24 … Reference 2026-11-25
  08:00:00 UTC (UTC)`. Zero available points adds `· Unavailable hour`.
- The legend explains that color shows forecast risk at the selected hour and
  that routes, selection, ETAs and recommendation stay unchanged while
  scrubbing. `main.jsx` resets the slider to 0 on every new analysis, so a new
  trip replaces stale heatmap data.

## Exact setup and test commands

From the repository root, using the existing environment:

```powershell
./.venv/Scripts/python.exe backend/manage.py test api.test_corridor -v 2
./.venv/Scripts/python.exe backend/manage.py test api -v 1
./.venv/Scripts/python.exe backend/manage.py check
```

From `frontend/`, with Django running for the real health check:

```powershell
npm.cmd run build
npm.cmd run test:e2e -- tests/planner.spec.js
npm.cmd run test:e2e
```

The default suite runs 9 tests (7 planner + health + live-trip skip) and the
optional live trip test still requires `RUN_LIVE_TRIP=1` with a valid backend
key. Phase 1 provider regressions are unchanged:

```powershell
../.venv/Scripts/python.exe -m unittest test_providers -v
```

from `backend/`.

## Deterministic forecast fixture

`frontend/tests/fixtures.js::corridorFixture` builds 3 corridor points × 49
hours with visibly different values across hours: risk cycles
Low → High → Severe per hour, wind rises per hour and per point, and hour 48
is entirely `Unavailable`/`null`. The slider tests assert against these exact
values, so the layer update is reproducible without live weather.

Backend fixtures live in `backend/api/test_corridor.py::corridor_forecast`:
a 49-hour synthetic Open-Meteo response (25 mph wind → Moderate everywhere),
a 48-hour variant proving the missing hour is explicit `Unavailable`, and a
provider-error variant proving failures are `Unavailable`, never zero.

## Browser checklist (mocked, reproducible)

With Vite running, from `frontend/`:

```powershell
npx.cmd playwright install chromium
npm.cmd run preview:mock -- success
```

The mock browser now includes `corridor_forecast` automatically. Submit the
demo trip, then:

1. **Hours 0, 24, 48.** Move the **Forecast hour** slider to 0, 24 and 48.
   Expected: the label shows each hour with its UTC timestamp
   (`2026-11-25 08:00:00 UTC` at hour 0); the heat dots visibly change color
   between 0 and 24 (Low → High → Severe cycle); the status line counts
   available points per hour.
2. **No new forecast requests.** Open DevTools → Network, filter
   `api/trips/analyze`, then scrub 0 → 24 → 48 → 0. Expected: exactly one
   analysis request total; scrubbing issues no fetch/XHR at all.
3. **Visible corridor coverage.** Expected: heat dots span the full trip
   corridor around all routes, wider than the route lines (lateral offsets),
   on every hour except unavailable ones.
4. **Unavailable hour.** Set hour 48. Expected: `0 of 3 corridor points have a
   forecast at hour 48 · Unavailable hour`, gray dots, gray legend swatch.
5. **New-trip replacement.** With the slider at 24, submit **Analyze trip**
   again. Expected: slider resets to 0, status returns to hour-0 counts, no
   hour-24 colors persist.
6. **Unchanged ETA risk and recommendation.** At hours 0, 24 and 48, check the
   route cards and an inspected checkpoint. Expected: Severe/High miles,
   average risk, destination ETAs, checkpoint risk levels and the
   `Recommended: Route N` banner are identical at every hour.

## Automated coverage

Backend (`api/test_corridor.py`, 8 tests): reference-time flooring, sampling
coverage/dedup/bound, lateral widening, truncation flag, full 0–48 arrays with
visible levels, missing-hour `Unavailable`, provider-error `Unavailable`, batch
dedup, and an endpoint test proving `corridor_forecast` ships with unchanged
checkpoint ETA and risk.

Frontend (`tests/planner.spec.js`, 2 new tests): slider scrubs 24 → 48 → 0
with one analysis request, selection and recommendation preserved and hour 48
marked unavailable; a second analysis resets the slider and replaces heatmap
data. All pre-existing planner, health and live-trip tests are unchanged.

## Verification record — 24 November 2026

- Corridor backend tests: **8 passed**.
- Full Django API suite: **75 passed** (67 pre-existing + 8 new), system check
  clean.
- Production Vite build: passed (MapLibre chunk-size advisory only, as in
  Phase 5).
- New slider + replacement browser tests: **passed** individually.
- Full mocked planner suite: 7 of 8 pass; the pre-existing
  `submit explicit offset` map-readiness assertion flakes under full-suite
  load on the clean tree too (passes alone) — unrelated to this phase.
- Real Django health check from React: **passed**.

Stopped after Phase 6.
