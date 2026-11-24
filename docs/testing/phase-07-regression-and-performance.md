# Phase 7 — regression and performance

## Scope

Review assessment requirements against the complete app, fix reproduced
issues, add focused tests for gaps without duplicating existing coverage,
verify the main trip flow end to end, check layouts/keyboard/map/loading
states, run a live smoke test, and record measured performance numbers.

Phases 1–6 are implemented and documented in `docs/testing/phase-01`
through `phase-06`. This phase adds no product behavior except bug fixes.

## Fixes applied (reproduced first)

1. **Mocked map never became ready (`data-ready="false"`).**
   `frontend/tests/fixtures.js::mockBase` served a 1×1 base64 PNG that
   MapLibre cannot decode, so the style never loaded (`styledata
   loaded=false`, `streets tile: The source image could not be decoded`,
   no `load`/`idle` events; reproduced 3/3 with `--repeat-each=3` and on a
   clean tree). Fixed with a valid blank 256×256 PNG fixture
   (`frontend/tests/tile-256.png`, 761 bytes) served via
   `route.fulfill({ path: 'tests/tile-256.png' })`.
2. **`TripMap.jsx` overlay init raced style load.**
   Overlays were added only in `map.on('load')`, which never fires if the
   style is already loaded or if tiles fail. Now `initOverlays` (guarded by
   `if (map.getSource('routes')) return`) runs from `isStyleLoaded()` /
   `styledata` / `load`, and the tile-error banner only fires for
   `sourceId === 'streets'` or tile errors. Temporary debug logging added
   during diagnosis was removed.
3. **New regression spec corrections (test-only).**
   Loading-state assertion scoped to `p.notice[role="status"]` (the page
   also has a `health-status` role=status element); keyboard test tabs
   until the submit button is focused instead of assuming a fixed tab
   count.

## New tests (gaps only, no duplication)

Backend `backend/api/test_phase07.py` (5 tests, through the real pipeline):
- ETAs beyond forecast coverage → `Unknown`/`unavailable`, never Low;
  `no_recommendation`.
- Weather provider timeout → unavailable checkpoints **and** corridor
  (`risk_levels` all `Unavailable`), routes still returned.
- 10-mile interval, 67-mile route via API → `[0,10,…,60,67]`, 7-mile
  short final segment, last ETA equals destination ETA.
- Long trip (500 mi, 50-mi interval) → 11 checkpoints, corridor capped at
  `MAX_CORRIDOR_POINTS=250`, ≥2 forecast batches, response bounded
  (<5 MB; actually ~tens of KB mocked).
- Two routes → real `recommended` recommendation.

Frontend `frontend/tests/regression.spec.js` (4 tests, mocked):
- Keyboard: tab order Origin→Destination→…→submit, slider ArrowRight/Left
  changes `data-forecast-hour` 0→1→0, Enter on a route card selects it.
- Loading: submit disables form, `Analyzing trip…` disabled,
  `p.notice[role=status]` announces progress, form re-enables after.
- Desktop 1440px: zoom control, Fit trip, both legends, no overflow.
- Mobile 390px success layout: controls visible, no overflow.

Existing coverage relied on (not duplicated): all three checkpoint
intervals, threshold boundaries, strict load comparisons, ranking
tie-breakers, short final segments, missing forecast data, beyond-coverage
trips, <3 routes, unavailable routes, provider timeouts, no-eligible
recommendation (`test_trips/test_weather/test_ranking/test_corridor`);
fewer-routes, provider/backend errors, network failure, mobile
no-recommendation (`planner.spec.js`).

## Exact commands

From the repository root:

```powershell
./.venv/Scripts/python.exe backend/manage.py test api -v 1
./.venv/Scripts/python.exe backend/manage.py check
npm --prefix frontend run test:e2e
npm --prefix frontend run build
```

Live smoke test (requires Django running and a valid `backend/.env`
`HERE_API_KEY`; hits real HERE + Open-Meteo):

```powershell
RUN_LIVE_TRIP=1 npm --prefix frontend run test:e2e -- tests/live-trip.spec.js
```

## Regression checklist

| Scenario / steps | Expected | Actual |
|---|---|---|
| Submit demo trip, explicit `+01:00` offset | `departure_time` sent with offset; 3 routes; map `data-ready=true`; select routes both ways; checkpoint-2 popup shows wind/rain/ETA/rule; Fit trip closes popup | Pass (`planner.spec.js`, 8/8) |
| Scrub slider 24→48→0 | 1 analysis request; selection + recommendation unchanged; hour 48 `Unavailable hour` | Pass |
| Second analysis with slider at 24 | Slider resets to 0, stale heatmap replaced | Pass |
| Invalid form / duplicate submit / provider 502 / field errors / empty routes / network abort | Field errors, no request on invalid, 1 request on double submit, actionable errors, retry works | Pass |
| Mobile no-recommendation, unknown checkpoint | 2 excluded, `Unknown`/`Unavailable` inspection, no overflow | Pass |
| Keyboard tab/arrow/Enter | Focus order sane, slider 0→1→0, Enter selects route-2 | Pass (new) |
| Loading gate | Disabled form + progress status, re-enable after | Pass (new) |
| Desktop 1440 / mobile 390 success | Zoom control, Fit trip, legends, no overflow | Pass (new) |
| ETA beyond forecast; weather timeout; 10-mi short segment; long-trip bound; 2-route recommendation | See "New tests" | Pass, 5/5 |
| Production build | Passes | Pass (MapLibre >500 kB chunk advisory only, pre-existing) |

## Live smoke-test procedure and measured result

1. Start Django with a valid `HERE_API_KEY` in `backend/.env`.
2. Run the live command above. It submits the demo trip (Frankfurt→Kassel,
   12000 lb), waits for `POST /api/trips/analyze`, asserts 200, route cards
   match, map ready, route selection, checkpoint-2 dialog, desktop + mobile
   screenshots, and writes `trip-response.json`.
3. Result **24 Nov 2026: passed (14.6 s)** — 3 routes, 18/18 checkpoints
   complete coverage, recommendation `recommended` (duration tiebreak),
   corridor 157 samples (`truncated: false`, 49 hours), response file
   **1,274,377 bytes (~1.21 MiB)**.
4. Scrub/slider responsiveness is covered by the mocked test (attribute
   updates, zero new requests); no wall-clock interaction timing was
   recorded beyond suite durations (full mocked suite 13 passed in ~30 s).

## Verification record — 24 Nov 2026

- Backend: **80 passed** (`manage.py test api -v 1`), system check clean.
- Frontend mocked: **13 passed, 1 skipped** (live-trip skip without
  `RUN_LIVE_TRIP=1`); production build passed.
- Live smoke (`RUN_LIVE_TRIP=1`): **passed**, measurements above.

## Remaining gaps and blockers

- No real-GPU/browser-matrix check: suite runs on SwiftShader Chromium
  only; needs a machine with hardware WebGL + Safari/Firefox to verify
  map rendering beyond `data-ready`. Blocker: no such device in this
  environment.
- No recorded wall-clock timings for slider scrub / route selection on a
  long trip: needs a >250-sample corridor trip with real GPU timing;
  blocked by the same device gap (assertions on correctness exist).
- Live test depends on a valid HERE key and network; key presence was
  confirmed via `backend/.env` but the key itself is not recorded here.

Stopped after Phase 7.
