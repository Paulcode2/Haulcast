# Phase 5 — trip planner and map

## Implemented workflow

The React/Vite app now submits the trip form to Django's
`POST /api/trips/analyze`. MapLibre GL JS renders every returned route with
OpenStreetMap raster tiles and attribution. Routing/geocoding credentials remain
in `backend/.env`; no HERE key is sent to the browser. The browser requests public
basemap tiles directly and sends trip-analysis requests only to Django.

Route cards and the map share a selected route. Clicking a route line, its R1/R2/R3
map button, or a route card selects it. The selected route is drawn thicker and
its checkpoint markers appear. All alternatives remain visible. The map fits the
whole trip after each successful analysis; **Fit trip** restores those bounds
after panning or inspecting a checkpoint.

The form has origin, destination, date/time, explicit departure UTC offset,
cargo weight and 10/25/50-mile interval. It validates locally and displays Django
field errors. Pending requests disable the form and are guarded against duplicate
submission. Provider/network errors, empty responses and no recommendation have
distinct messages. Old results are cleared when a new request starts.

## Startup

Use the existing virtual environment; do not recreate it from its own Python.
From the repository root, terminal 1:

```powershell
./.venv/Scripts/python.exe backend/manage.py runserver 127.0.0.1:8000
```

Ensure `backend/.env` contains a working `HERE_API_KEY`. Open-Meteo requires no
key for these checks. Terminal 2:

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```

Open **http://127.0.0.1:5173**. `frontend/.env` uses
`VITE_API_BASE_URL=http://127.0.0.1:8000`. Both localhost origins on port 5173 are
allowed by the existing Django CORS configuration. Restart Vite after changing
its environment. On macOS/Linux use `npm`, `python3` and `.venv/bin/python`.

The map requires WebGL. When WebGL is unavailable, route cards and the checkpoint
list still provide the results. Failed basemap requests show a notice; route
data is still available. Production deployment should choose an appropriately
provisioned basemap service; this local assessment uses standard public OSM tiles.

## Departure time semantics

The selected datetime is a wall-clock value, not implicitly interpreted using
the browser's timezone. The UTC-offset selector is explicit and defaults to
**UTC+00:00**. The **Sending** preview shows the exact datetime that will be sent.

Example: selecting **25 November 2026, 09:00**, with **UTC+01:00**, sends
`2026-11-25T09:00:00+01:00`, equal to 08:00 UTC. Changing to UTC+00:00 sends
09:00 UTC. Offsets from UTC−12:00 through UTC+14:00 are available in 15-minute
steps. This is a fixed-offset selector, not an IANA timezone selector; the UI
explicitly asks the user to choose the correct offset for the location and date.
Daylight-saving changes are not inferred. All ETAs and forecast timestamps in
results and popups are visibly labeled **UTC**.

## Demo trip: browser walkthrough

1. Click **Use demo trip**. Expected: Frankfurt am Main, Germany → Kassel,
   Germany; tomorrow at 09:00; UTC+00:00; cargo 12,000 lb; interval 25 miles.
   On the verification date, tomorrow is **2026-11-25**. For later runs, use the
   newly generated tomorrow rather than an expired forecast date.
2. Click **Analyze trip**. Expected: **Analyzing trip…**, disabled inputs/button,
   and a status message about routes and forecasts. Only one POST is made even
   if you try to submit again while pending. The frontend timeout is 120 seconds.
3. Expected success: route count, submitted trip/departure, recommendation and
   explanation, a fitted map, and one card per returned route. Three routes were
   returned in the live check, but HERE may legitimately return fewer.
4. Read each card: distance, duration, destination ETA, Severe/High/No Travel miles,
   unknown coverage miles, average score on the backend's 0–4 scale, and eligibility
   or exclusion reasons. Display values are rounded; ranking remains backend-owned.
5. Click **Route 2** in its card. Expected: card border/pressed state changes,
   route 2 is emphasized on the map, and its numbered checkpoints/list appear.
6. Click **R3** on the map (or an unshared portion of route 3's line). Expected:
   route 3's card becomes selected. On shared geometry, use the labeled R buttons
   or cards to choose a particular route without ambiguity.
7. Click numbered checkpoint **2** on the map. Expected popup: distance, ETA,
   risk level, coverage, wind mph, rain and snow in/hr, per-field forecast UTC
   timestamps and the triggering rule. The map pans to keep the popup in view;
   scroll within the popup for long details. The same full details appear below
   the checkpoint list, providing a keyboard-accessible alternative.
8. Close the popup and click the marker again; it should reopen. **Fit trip**
   closes inspection and restores whole-trip bounds. Selecting another route
   clears the previous checkpoint inspection.

Risk has color **and text**: the legend labels every level; checkpoint buttons
have accessible names containing their risk, and checkpoint-list buttons include
the risk and incomplete status. Unknown is gray, distinct from green Low.
Dashed marker outlines mean incomplete coverage. Missing forecast values display
**Unavailable**, never zero. Confirmed No Travel remains visible with incomplete
coverage, matching the backend response.

## Mobile-width check

1. Open browser DevTools responsive mode and set **390 × 844**.
2. Run the demo or the `no-recommendation` fixture below.
3. Expected: one-column layout, full-width form controls, visible map, stacked
   route cards, wrapped checkpoint buttons, and no page-level horizontal scroll.
4. Select another route using its card; inspect a checkpoint using the list or
   map. Expected: map selection stays synchronized; details remain readable.
5. Inspect Unknown weather in the fixture. Expected **Unknown**, **Incomplete**,
   and **Unavailable** values, not a green/Low conclusion. The map popup has a
   bounded, scrollable content area and the complete text remains below the map.

## Repeatable mock scenarios

Fixtures are in `frontend/tests/fixtures.js`. Mocking happens only in a separate
Playwright browser; there is no mock response path in production frontend code.
The mock browser intercepts health, analysis and tiles. Tiles are a blank PNG
for deterministic rendering; MapLibre, route geometry, marker clicks and popups
are real. These simplified UI fixtures are not live weather or ranking evidence.

With Vite running, from `frontend/`:

```powershell
npx.cmd playwright install chromium
npm.cmd run preview:mock -- success
```

A separate visible browser opens with the demo fields populated. Click
**Analyze trip**. Close that browser to end the helper. Choose another scenario:

| Command suffix | Steps and expected result |
| --- | --- |
| `success` | Submit; 3 cards, route 1 recommended. Switch cards/map and inspect checkpoint 2. |
| `fewer` | Submit; exactly **1 route to compare**, one card/route; no fabricated alternatives. |
| `no-recommendation` | Submit; no recommendation, all routes excluded. Inspect checkpoint 2: Unknown and unavailable weather. Route 1 also shows a confirmed No Travel exclusion. |
| `provider-error` | Submit; HTTP 502 fixture produces the HERE authentication error banner. Form becomes enabled for retry. |
| `field-error` | Submit; HTTP 400 fixture displays **Use a more specific origin.** beside Origin and a general error banner. |
| `empty` | Submit; HTTP 200 with no routes displays **No routes returned** and no cards. |
| `slow` | Submit; response waits 5 seconds. Inputs and submit remain disabled. DevTools Network shows one analysis request. |

For example:

```powershell
npm.cmd run preview:mock -- fewer
npm.cmd run preview:mock -- provider-error
npm.cmd run preview:mock -- no-recommendation
```

Run one helper at a time and close its browser before starting another.

### Invalid form input without a provider call

In a normal fresh page, leave Origin, Destination and Cargo blank and submit.
Expected inline errors; focus moves to Origin; no analysis request is sent.
Then populate demo fields and change cargo to `0` or `-1`; clear departure and
submit again. Expected positive-weight and date/time errors. The interval control
allows only 10, 25 and 50. API-supplied validation still appears inline if the
server rejects a field. Use `field-error` above to reproduce that case reliably.

### Network and provider failures

The automated network test aborts the analysis request and checks the actionable
backend/CORS message and enabled retry button. To reproduce manually, block
`*/api/trips/analyze` in DevTools Network request blocking and submit. Remove the
block before retrying. Do not change real HERE credentials merely to test errors;
use the provider-error fixture. Genuine Django/provider errors are displayed from
the backend's sanitized `error.message`.

## Exact automated commands

From `frontend/`, with Django running for the real health check:

```powershell
npm.cmd run build
npm.cmd run test:e2e
```

The default suite runs 7 tests and skips the optional live trip test. For fully
offline workflow checks, run only the six mocked planner tests:

```powershell
npm.cmd run test:e2e -- tests/planner.spec.js
```

Playwright starts Vite if necessary and reuses port 5173 if already running.
Tests enable Chromium's software WebGL renderer so MapLibre is exercised even
on environments without GPU acceleration.

Optional live trip check with a valid backend key and Django running:

```powershell
$env:RUN_LIVE_TRIP = '1'
npm.cmd run test:e2e -- tests/live-trip.spec.js
Remove-Item Env:RUN_LIVE_TRIP
```

This submits the actual demo through React, checks the HTTP 200 result, selects
another returned route, inspects a map checkpoint, checks desktop/mobile layouts,
and saves full-page screenshots and the response under the gitignored
`frontend/test-results/` directory. No API response or map tiles are mocked in
that live test. Subsequent test runs may replace those local artifacts.

Backend regression command, from the repository root:

```powershell
./.venv/Scripts/python.exe backend/manage.py test api -v 1
```

## Verification record — 24 November 2026

- Production Vite build: passed. MapLibre adds a large map bundle; Vite reports
  a nonfatal chunk-size advisory.
- Six mocked planner browser tests and the real Django health test: passed.
- Optional live Chromium workflow: passed against actual Django, HERE and
  Open-Meteo, including route selection and a checkpoint popup.
- Live demo: Frankfurt am Main → Kassel, **2026-11-25 09:00 UTC**, 12,000 lb,
  25-mile interval; **3 routes returned** and route 1 recommended.
- Desktop (1440 px) and mobile (390 px) screenshots inspected. The initial
  inspection found a clipped popup; its placement and height were corrected and
  a browser assertion now checks that the popup stays inside the map.
- All **67 backend API tests passed**.
- Dependency audit after updating to the patched MapLibre release: **0 vulnerabilities**.

Stopped after Phase 5.
