# Weather-Aware Truck Routing (Haulcast)

Plan truck trips with weather-aware risk: enter origin, destination,
departure time, cargo weight, and checkpoint spacing; the Django API
returns up to 3 HERE truck routes with distance checkpoints, UTC ETAs,
ETA-matched Open-Meteo forecasts, per-checkpoint risk levels, corridor
heatmap data, distance-weighted route summaries, and an
eligibility-filtered recommendation. The React/Vite planner renders
routes on a MapLibre map, supports route selection both ways, checkpoint
weather inspection, and a 0–48h forecast slider that only recolors the
heatmap.

## Status

- **Hosted URL: none yet — NOT YET DEPLOYED.** No live demo URL exists.
  See [Phase 8](docs/testing/phase-08-production-verification.md) for
  deploy steps and blockers (hosting account + host `HERE_API_KEY`).
- Repo: `https://github.com/Paulcode2/Haulcast`, branch `main`.

## Local setup

Requirements: Python 3.12+ (3.14 used here), Node.js 22.12+ (24.14 used
here), npm, internet access.

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r backend/requirements.lock.txt
Copy-Item backend/.env.example backend/.env
Copy-Item frontend/.env.example frontend/.env
cd frontend
npm.cmd ci
cd ..
```

Do not overwrite an existing `.env` on repeat setup. On macOS/Linux use
`python3`, `.venv/bin/python`, `cp`, `npm`. On this Windows box use
`npm.cmd` (avoids the `npm.ps1` restriction).

Run (repo root, two terminals):

```powershell
./.venv/Scripts/python.exe backend/manage.py runserver 127.0.0.1:8000 --noreload
cd frontend
npm.cmd run dev
```

Open `http://127.0.0.1:5173` → expect **Backend connected**. No Vite
proxy: the browser calls Django directly, exercising CORS.

## Environment variables

| Variable | File | Purpose / default |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | `backend/.env` | Required Django secret; example is dev-only |
| `DJANGO_DEBUG` | `backend/.env` | `true` locally; production `false` |
| `DJANGO_ALLOWED_HOSTS` | `backend/.env` | Comma-separated hosts; default `localhost,127.0.0.1` |
| `CORS_ALLOWED_ORIGINS` | `backend/.env` | Exact frontend origins; default both localhost `:5173` forms |
| `HERE_API_KEY` | `backend/.env` | Backend-only HERE key (Geocoding & Search + Routing v8, truck); blank = live routing disabled |
| `VITE_API_BASE_URL` | `frontend/.env` | Public Django origin; default `http://127.0.0.1:8000` |
| `DJANGO_SECURE_SSL_REDIRECT` | prod env | `true` behind HTTPS |
| `DJANGO_SESSION_COOKIE_SECURE` / `DJANGO_CSRF_COOKIE_SECURE` | prod env | `true` behind HTTPS |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | prod env | `https://<frontend-host>` |
| `DJANGO_SECURE_HSTS_SECONDS` (+ subdomains/preload) | prod env | e.g. `31536000` once fully HTTPS |
| `DJANGO_LOG_LEVEL` | both | Default `INFO` |

Process env wins over `.env`. Never put a HERE key in `VITE_*`,
frontend source, shell history, or screenshots. Production template:
`backend/.env.production.example`. Never commit a filled-in `.env`.

## Test commands

Backend (repo root):

```powershell
./.venv/Scripts/python.exe backend/manage.py check
./.venv/Scripts/python.exe backend/manage.py check --deploy   # with production-like env
./.venv/Scripts/python.exe backend/manage.py test api -v 1   # 80 tests
```

Phase 1 provider checker (from `backend/`):

```powershell
../.venv/Scripts/python.exe -m unittest test_providers -v
```

Frontend (from `frontend/`, Django running for the health check):

```powershell
npm.cmd run build
npm.cmd run test:e2e -- tests/planner.spec.js
npm.cmd run test:e2e
```

Default e2e is mocked/offline; the live-trip test needs `RUN_LIVE_TRIP=1`
plus a valid backend key.

## Demo trip

Click **Use demo trip** → **Analyze trip**:

- Frankfurt am Main, Germany → Kassel, Germany; tomorrow 09:00 UTC;
  cargo 12,000 lb; interval 25 miles.
- Expect: route cards with distance/duration/destination ETA,
  Severe/High/No-Travel/unknown miles, average score, eligibility or
  exclusion reasons; recommendation banner with explanation; fitted map
  with `data-ready=true`; click card ↔ map line/R1–R3 selects both ways;
  checkpoint dialog shows wind/rain/ETA/rule.
- Scrub **Forecast hour** 0→24→48: heat dots recolor from loaded data
  only (one analysis request total); cards, selection, ETAs,
  recommendation unchanged; hour 48 mocked run shows
  `Unavailable hour` with gray dots.
- Live reference (25 Nov 2026): 3 routes, 18/18 checkpoints complete.
  HERE may legitimately return fewer than 3 — still success; the server
  never invents alternatives.

## Risk-boundary decisions (`backend/api/risk.py`)

Pure function of mph, in/hr, cargo lb. Highest single-field rating wins;
reasons name every field at that top rating.

- Wind (mph): <25 Low; ≥25 Moderate; ≥35 High; ≥45 Severe; ≥55 No Travel.
- Rain (in/hr, preceding-hour total ÷ 1h): <0.10 Low; ≥0.10 Moderate;
  ≥0.25 High; ≥0.50 Severe; >1.00 No Travel (exactly 1.00 stays Severe).
- Snow (in/hr water-rate from cm depth): <0.5 Low; ≥0.5 Moderate;
  ≥1.0 High; ≥2.0 Severe; >3.0 No Travel (exactly 3.0 stays Severe).
- Cargo overrides (strict `>`): wind 45–<55 with cargo >30,000 lb →
  No Travel; wind 35–<45 with cargo >40,000 lb → Severe.
- Missing/invalid field (null, NaN, negative, bool): field skipped,
  listed in `missing_fields`, `coverage_complete=false`,
  `assessment_status=incomplete` — unless a confirmed No Travel already
  holds (`assessment_status=confirmed` still reports partial coverage).
  All fields missing → `Unknown`. No zero-fill, no nearby-hour reuse.

## ETA assumptions

- Distances follow decoded-polyline haversine (R = 6,371,008.8 m;
  1 mi = 1,609.344 m), not straight lines, nominal intervals, or HERE
  road-network totals (both distances are returned; checkpoints use
  geometry miles, 6-decimal output).
- Origin + destination always included; interior checkpoints every
  10/25/50 mi (default 25); endpoint within 0.1 m of an interval appears
  once; short final segment kept (e.g. 0/25/50/67).
- Timing spreads each section's summary duration by span weights (span
  durations weight geometry distance within the span); unlocated
  pre/post-action time spreads proportionally. Invalid/absent spans fall
  back to distance interpolation within that section
  (`timing_methods` exposes which path applied).
- `destination_eta` = departure + `duration_seconds`; final checkpoint
  ETA equals it exactly. All ETAs UTC ISO8601. These are estimated
  travel ETAs, not a stop/wait schedule.

## Segment risk method

Per consecutive checkpoint pair, length from unrounded cumulative
`distance_meters` (rounded `distance_miles` never used for ranking):

1. Both endpoints complete + known → higher rating wins.
2. Either endpoint confirmed No Travel → segment No Travel (even beside
   Unknown/incomplete).
3. Otherwise any incomplete coverage → Unknown (a partial endpoint's
   best rating is not final — missing weather could raise it).

`average_risk = Σ(segment_mi × score) / Σ(segment_mi)` with
Low 0 / Moderate 1 / High 2 / Severe 3 / No Travel 4; null if any
segment is Unknown (unknown miles are never zeroed or dropped).
`severe_miles` / `high_miles` / `no_travel_miles` count exact-rating
miles; `unknown_coverage_miles` adjoins incomplete checkpoints and may
overlap No Travel miles (do not sum them as a partition).
`summary.display` rounds to 2 decimals for presentation only — ranking
uses raw floats.

## Recommendation exclusions

A route is excluded when either holds (both reported when both hold):

- `no_travel_segments` — ≥1 No Travel segment.
- `incomplete_forecast_coverage` — ≥1 checkpoint without full coverage.

Eligible routes compare lexicographically on raw values: fewest Severe
miles → fewest High miles → lowest average risk → shortest
`duration_seconds`. Exact tie on all four keeps provider order with
`deciding_factor=exact_tie`; one eligible route →
`only_eligible_route`. All excluded → HTTP 200, all routes + reasons,
`recommended_route_id=null`, `status=no_recommendation` (no fallback to
an unsafe route). HERE returning zero routes is HTTP 422 `no_routes`.

## Checkpoint ETAs vs forecast slider

- **Checkpoint ETAs** are fixed travel estimates from departure +
  routing durations, each paired with the single forecast hour selected
  for that ETA (wind: nearest hour, later on :30; rain/snow: interval
  `(t−1h, t]` containing the ETA). They never move when scrubbing.
- **Forecast slider** (0–48 from floored-UTC-hour reference) only
  recolors the corridor heatmap from already-loaded
  `corridor_forecast` data (49 hourly values per sampled point, lateral
  ±6 mi offsets, ≤250 points). Scrubbing issues no requests and leaves
  geometry, selection, ETAs, summaries, and recommendation unchanged.
  Missing hours are explicit `Unavailable`/gray, never interpolated.
  A new analysis resets the slider to 0 and replaces stale heat data.

## Deploy

- API (Docker or Procfile): `pip install -r
  backend/requirements.lock.txt`, env from
  `backend/.env.production.example`, `collectstatic`, then
  `gunicorn config.wsgi --bind 0.0.0.0:$PORT` from `backend/`.
- Frontend (static): set `VITE_API_BASE_URL` to the API host at build
  time, `npm --prefix frontend ci && npm --prefix frontend run build`,
  serve `frontend/dist/`. Or `render blueprint launch` with `render.yaml`.
- Details, verification evidence, diagnosis, and blockers:
  [Phase 8](docs/testing/phase-08-production-verification.md).

## Testing guides

- [Phase 1 setup and providers](docs/testing/phase-01-setup-and-providers.md)
- [Phase 2 route API](docs/testing/phase-02-routes-checkpoints-and-etas.md)
- [Phase 3 weather and risk](docs/testing/phase-03-weather-and-checkpoint-risk.md)
- [Phase 4 route ranking](docs/testing/phase-04-route-ranking.md)
- [Phase 5 planner and map](docs/testing/phase-05-trip-planner-and-map.md)
- [Phase 6 heatmap and slider](docs/testing/phase-06-heatmap-and-forecast-slider.md)
- [Phase 7 regression and performance](docs/testing/phase-07-regression-and-performance.md)
- [Phase 8 production verification](docs/testing/phase-08-production-verification.md)
