# Phase 2 — routes, checkpoints and ETAs

## Scope

Adds `POST /api/trips/analyze` (trailing slash also accepted) to the existing
Django REST Framework backend. Uses the Phase 1 HERE endpoints, credentials,
Flexible Polyline dependency and local CORS setup. No database, weather sampling,
weather scoring or new frontend workflow is added in this phase.

## Run and test

Use the existing `.venv`; do not recreate it while it is active. No new packages
are required. From the repository root:

```powershell
./.venv/Scripts/python.exe backend/manage.py test api -v 2
./.venv/Scripts/python.exe backend/manage.py check
```

Phase 1 provider-checker regression tests, from `backend/`:

```powershell
../.venv/Scripts/python.exe -m unittest test_providers -v
```

The API tests use deterministic provider fixtures; they require no credential
and make no third-party calls. For fresh dependency installation, follow the
[Phase 1 guide](phase-01-setup-and-providers.md).

## Live request

Set `HERE_API_KEY` in `backend/.env` and restart Django if it was already running:

```powershell
./.venv/Scripts/python.exe backend/manage.py runserver 127.0.0.1:8000
```

In another terminal at the repository root:

```powershell
curl.exe -i -X POST http://127.0.0.1:8000/api/trips/analyze -H "Content-Type: application/json" --data-binary "@docs/testing/phase-02-request.json"
```

On macOS/Linux use `curl` and `.venv/bin/python`. In Postman choose POST, the
same URL, Body → raw → JSON, and paste:

```json
{
  "origin": "Frankfurt am Main, Germany",
  "destination": "Kassel, Germany",
  "departure_time": "2026-11-25T09:00:00+01:00",
  "load_weight_lbs": 12000,
  "checkpoint_interval_miles": 25
}
```

For later dates, use a future departure (for example tomorrow at 09:00 in
Europe/Berlin with its seasonal offset). Past dates are not rejected locally;
HERE determines availability. The example trip remains a candidate, not a
verified guarantee of three alternatives.

## Request contract

| Field | Validation |
| --- | --- |
| `origin`, `destination` | Required nonblank strings, trimmed, maximum 500 characters each |
| `departure_time` | Required ISO8601 datetime with seconds and explicit `Z` or `±HH:MM`; optional fractional seconds, 1–6 digits; calendar and offset validated |
| `load_weight_lbs` | Required finite positive numeric cargo weight in pounds; numeric strings accepted, booleans rejected |
| `checkpoint_interval_miles` | 10, 25 or 50; defaults to 25 when omitted; null and booleans rejected |

Cargo weight is echoed as `load_weight_lbs`, with `weight_semantics=cargo_only`.
It is **not** sent as HERE `vehicle[currentWeight]` or `vehicle[grossWeight]`.
Those describe the actual vehicle combination and its permitted gross weight,
respectively; cargo alone cannot supply either. Routing uses the default truck
profile until vehicle specifications are introduced in a separate phase.

The server geocodes both locations and uses the first result's access position
when available, otherwise its position. It sends `transportMode=truck`,
`routingMode=fast`, `alternatives=2`, the supplied `departureTime`,
`return=polyline,summary`, and `spans=duration,length,segmentRef` to HERE.

## Expected successful response

HTTP 200 contains:

| Field | Meaning |
| --- | --- |
| `origin`, `destination` | Selected geocoding result with `query`, `label`, `latitude`, `longitude` |
| `departure_time` | Validated departure with its explicit offset |
| `load_weight_lbs`, `weight_semantics` | Cargo input and its meaning |
| `checkpoint_interval_miles` | Selected/default interval |
| `route_count` | Number of distinct routes actually returned |
| `routes[].id` | HERE route ID, or geometry-derived ID if absent |
| `routes[].distance_meters`, `distance_miles` | Sum of HERE section summary lengths |
| `routes[].geometry_distance_miles` | Cumulative decoded geometry distance used for checkpoints |
| `routes[].duration_seconds` | Sum of HERE section summary durations |
| `routes[].geometry` | GeoJSON `LineString`, coordinates in **[longitude, latitude]** order |
| `routes[].destination_eta` | UTC ISO8601 timestamp, departure plus total duration |
| `routes[].timing_methods` | `span_duration_weights`, `section_distance_approximation`, or both for mixed sections |
| `routes[].checkpoints` | Ordered list of `index`, `distance_miles`, `latitude`, `longitude`, `eta` |

HERE can return fewer than three routes. One or two routes is a successful result;
the server does not manufacture alternatives. Geometry fingerprints (coordinates
rounded to five decimal places) remove identical decoded paths, preserving provider
order and the primary route first. This detects repeated geometry, not every
possible equivalent path sampled with different intermediate vertices.

## Checkpoint placement and timing

Distance is accumulated segment by segment using the haversine formula with a
mean Earth radius of 6,371,008.8 m; one mile is exactly 1,609.344 m. Interior
checkpoints are interpolated along decoded segments at each requested interval,
including the short longitude direction when crossing the antimeridian. These
are geometry distances, not point-to-point distance from the origin. The origin
and destination are always included. An endpoint within 0.1 m of an interval is
included only once, avoiding floating-point/encoded-polyline duplicate endpoints.
Distances in checkpoint output are rounded to six decimal places.

HERE's road-network summary distance can differ slightly from decoded-polyline
distance. Both are returned explicitly. The final checkpoint matches
`geometry_distance_miles`, not necessarily `distance_miles`.

Timing uses each section's duration separately. Valid span offsets index that
section's geometry; span durations determine relative travel-time weights.
Within a span, time is interpolated by geometry distance. Weights are normalized
to the section's total summary duration, ensuring the destination time includes
the total duration even when span travel time and section totals differ.
This spreads any unlocated pre/post-action time proportionally: these are
estimated travel ETAs, not a precise stop/wait schedule. Raw provider arrival
timestamps are not used as separate conflicting anchors.

If spans are absent, invalid, or have zero durations, timing falls back to
distance interpolation **within that section**. With only one total duration,
this becomes `departure + total_duration × checkpoint_distance / geometry_length`.
The response exposes the fallback via `timing_methods`. UTC output avoids
confusing origin offsets with destination timezone changes. The last checkpoint
ETA is exactly `destination_eta`, equal to departure plus `duration_seconds`.

## Deterministic examples and assertions

`CheckpointTests.test_67_miles_all_intervals_and_destination_eta` constructs an
equatorial polyline with vertices at 0, 20 and 67 miles. It uses 4,020 seconds
(67 minutes) total, departing `2026-11-25T09:00:00+01:00`:

| Interval | Checkpoint distances (miles) |
| --- | --- |
| 10 | 0, 10, 20, 30, 40, 50, 60, 67 |
| 25 | **0, 25, 50, 67** |
| 50 | 0, 50, 67 |

For 25 miles, the UTC ETAs are `08:00:00Z`, `08:25:00Z`, `08:50:00Z`, and
`09:07:00Z` on 25 November 2026. This fixture is synthetic and does not claim
to be a live HERE route.

`test_exact_multiple_has_one_destination_for_every_interval` checks 20 miles
at interval 10, 50 miles at interval 25, and 100 miles at interval 50. Each has
exactly three checkpoints: `[0, interval, 2 × interval]`, with one destination.
Other tests cover short routes, GeoJSON coordinate order, multi-section joins,
nonuniform span timing, fallback timing, distinct-route counts, and errors.

For each live interval (edit the JSON to 10, 25, then 50), verify:

1. The first checkpoint is at mile 0 and its ETA equals departure as an instant.
2. Interior checkpoint distances are consecutive interval multiples.
3. The final checkpoint uses the last geometry coordinate and matches geometry
   length within rounding tolerance; it is not duplicated.
4. Parse ETAs as datetimes, not local display strings: they increase in order.
5. Final checkpoint ETA equals `destination_eta`; subtracting departure gives
   `duration_seconds` (allow microsecond serialization rounding).
6. `route_count` equals the route array length, including when fewer than three
   distinct routes are supplied.

## Validation and error reproduction

Validation failures return HTTP 400:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Check the request fields.",
    "fields": {"load_weight_lbs": ["Enter a finite positive cargo weight in pounds."]}
  }
}
```

Edit the copyable request and repeat curl/Postman with blank origin/destination,
missing required fields, `load_weight_lbs` set to `0`, `-1`, `"NaN"`,
`"Infinity"`, or `true`, interval `11` or null, or departure without an offset.
Use quoted nonfinite strings because raw NaN/Infinity are not valid JSON.
Also try `2026-02-30T09:00:00+01:00` and an invalid offset such as `+01:99`.
Provider calls must not occur for these invalid inputs.

Provider failures use `{"error":{"code":"...","message":"..."}}`:

| HTTP | Code | Reproduction |
| --- | --- | --- |
| 503 | `provider_not_configured` | Blank/unset backend key, restart server, send valid request |
| 422 | `geocoding_not_found` | A location for which HERE returns empty `items`; deterministic test also covers both origin and destination failures |
| 422 | `no_routes` | HERE returns empty `routes`; fixture tests reproduce without depending on changing road availability |
| 502 | `provider_error` | Temporarily use an invalid local HERE key, restart, send valid request; also covers quota, HTTP and connection failures |
| 502 | `invalid_provider_response` | Malformed provider data or unusable geometry/timing; deterministic fixtures |
| 504 | `provider_timeout` | Provider request exceeds 30 seconds; deterministic timeout fixture |

Do not replace valid credentials just to reproduce an error if other work uses
them. The following exact offline command exercises error mapping and request
validation safely:

```powershell
./.venv/Scripts/python.exe backend/manage.py test api.test_trips.ProviderTests api.test_trips.TripAPITests -v 2
```

Raw provider error bodies, keyed URLs and credentials are never included in API
errors. A malformed route fails the request with 502 rather than returning an
invented geometry or silently reporting an incomplete success.

## Execution record — 24 November 2026

- Django tests: **23 passed**, including 21 Phase 2 tests and 2 existing health/CORS tests.
- Django system check: **passed**, no issues.
- Phase 1 provider-checker regressions: **3 passed**.
- Local HTTP smoke through Django's WSGI application: **passed** for the
  missing-credential path; a valid POST returned HTTP 503 with
  `error.code=provider_not_configured`.
- Live HERE smoke test: **BLOCKED — `HERE_API_KEY` is still missing**. No live
  geocoding or routing success is claimed. Set the backend key and run the request
  above to complete verification.

## Provider references

- [HERE span offsets and timing metadata](https://docs.here.com/routing/docs/routing-v8-span)
- [HERE section summaries and units](https://docs.here.com/routing/docs/routing-v8-route-summary)
- [HERE vehicle properties](https://docs.here.com/routing/docs/routing-v8-vehicle-properties)
- [HERE route sections and travel versus full section timing](https://docs.here.com/routing/docs/routing-v8-route-section)
