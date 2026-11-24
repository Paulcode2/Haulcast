# Phase 1 — setup and providers

## Scope and prerequisites

The workspace was empty on inspection. This repository introduces React + Vite
in `frontend/`, Django REST Framework in `backend/`, and a standalone backend
provider checker. There is no trip analysis, route scoring, map or persistence yet.

Requirements: Python 3.12+ (3.14 used here), Node.js 22.12+ (24.14 used here),
npm, internet access, and enough disk space for dependencies and a browser.
For HERE, create an application/API key with access to Geocoding & Search v7
and Routing v8, including truck routing. Open-Meteo's public forecast endpoint
needs no key for this assessment; review its terms before commercial deployment.

## Environment and installation

From the repository root, PowerShell:

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r backend/requirements.lock.txt
Copy-Item backend/.env.example backend/.env
Copy-Item frontend/.env.example frontend/.env
cd frontend
npm.cmd ci
cd ..
```

Do not overwrite an existing `.env` when repeating setup. On this machine,
Windows' `python`/`py` aliases were inaccessible; the working interpreter was
`C:/Users/HP/AppData/Local/Python/bin/python.exe`. `npm.cmd` avoids PowerShell's
restriction on `npm.ps1`. On macOS/Linux use `python3`, `.venv/bin/python`,
`cp` and `npm` instead.

| Variable | Location | Purpose |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | `backend/.env` | Required Django secret; example is local development only |
| `DJANGO_DEBUG` | `backend/.env` | `true` locally; defaults to `false` |
| `DJANGO_ALLOWED_HOSTS` | `backend/.env` | Comma-separated hosts, default `localhost,127.0.0.1` |
| `CORS_ALLOWED_ORIGINS` | `backend/.env` | Exact frontend origins, default both localhost forms on port 5173 |
| `HERE_API_KEY` | `backend/.env` | Geocoding and routing secret; blank example |
| `VITE_API_BASE_URL` | `frontend/.env` | Public Django origin, default `http://127.0.0.1:8000` |

Process environment variables take precedence over `.env`. Provider URLs are
fixed in the backend checker. Never put a HERE key in `VITE_*`, frontend source,
shell history or screenshots. `.gitignore` excludes `.env` and `.env.*` except
`.env.example`, local dependencies and generated evidence. The checker suppresses
HTTP URLs/error bodies and writes request parameters without the API key.
`requirements.txt` declares supported dependency ranges; `requirements.lock.txt`
and `frontend/package-lock.json` capture the versions installed for verification.

## Start and verify both apps

Terminal 1, repository root:

```powershell
./.venv/Scripts/python.exe backend/manage.py check
./.venv/Scripts/python.exe backend/manage.py test api
./.venv/Scripts/python.exe backend/manage.py runserver 127.0.0.1:8000 --noreload
```

Terminal 2:

```powershell
cd frontend
npm.cmd run dev
```

Open `http://127.0.0.1:5173`. Expect **Backend connected**; click **Check
connection** to repeat the real cross-origin request. There is no Vite proxy,
so this exercises Django CORS. The dev server refuses a different port.

```powershell
curl.exe -i -H "Origin: http://127.0.0.1:5173" http://127.0.0.1:8000/api/health/
```

Expected HTTP 200, `Access-Control-Allow-Origin: http://127.0.0.1:5173`, and
`{"status":"ok","service":"weather-aware-truck-routing"}`.
This is an application health check, not a third-party availability check.

With Django still running, automated browser check and production build:

```powershell
cd frontend
npx.cmd playwright install chromium
npm.cmd run test:e2e
npm.cmd run build
```

The browser test starts Vite and waits for React to show the result of a real
Django request; no network mocks are used. Backend tests also verify that an
untrusted Origin gets no CORS allow header.

## Live provider checks

All commands below run from `backend/`. Output paths are relative to that
directory. Exit codes: `0` all selected checks passed, `1` a check failed,
`2` a check was blocked. Read the JSON evidence for detailed failures.

Offline checker tests (these do not substitute for live HERE verification):

```powershell
../.venv/Scripts/python.exe -m unittest test_providers -v
```

### Open-Meteo

```powershell
../.venv/Scripts/python.exe check_providers.py --provider weather --output ../docs/testing/results/weather.json
```

This calls `GET https://api.open-meteo.com/v1/forecast` with:

```text
latitude=50.1109
longitude=8.6821
hourly=wind_speed_10m,rain,snowfall
wind_speed_unit=kmh
precipitation_unit=mm
timeformat=iso8601
timezone=UTC
forecast_days=2
```

Expected: 48 consecutive hourly records, equal-length non-null numeric arrays,
and `utc_offset_seconds=0`. Inspect `hourly_units` rather than inferring units.

| Field | Returned unit | Meaning |
| --- | --- | --- |
| `wind_speed_10m` | `km/h` | Wind speed at 10 m, instantaneous at the timestamp |
| `rain` | `mm` | Large-scale rain accumulated over the preceding hour |
| `snowfall` | `cm` | Snowfall depth accumulated over the preceding hour |

`rain` is not total precipitation: showers are a separate variable. `precipitation`
includes rain, showers and snow water equivalent. Snowfall remains **cm** even
when `precipitation_unit=mm`. The provider returns ISO8601 strings such as
`2026-11-24T00:00` without a `Z`; interpret these using the response timezone
and offset, not the browser's local timezone. The observed UTC request returned
`timezone=GMT`, `timezone_abbreviation=GMT`, `utc_offset_seconds=0`.
Use UTC internally in a later phase; do not align weather against local route
timestamps without converting them. This phase only validates a standalone
weather point, not weather sampled along routes.

### HERE geocoding and truck routing

1. Set `HERE_API_KEY` in `backend/.env` locally.
2. Run the bounded candidate search:

```powershell
../.venv/Scripts/python.exe check_providers.py --provider here --search-demo --output ../docs/testing/results/here-demo.json
```

3. Inspect `here.attempts`. Each attempt geocodes both locations using
   `GET https://geocode.search.hereapi.com/v1/geocode` with `q`, `limit=1`,
   and the backend key. Expect non-empty `items`, a matching `title`, and
   `position.lat/lng`. The report records the selected result. Confirm the
   returned locality matches the intended place; the first result is only
   a Phase 1 convenience. Routing uses `access[0]` when supplied, otherwise
   `position`.
4. The checker requests `GET https://router.hereapi.com/v8/routes` with
   geocoded `origin` and `destination`, `transportMode=truck`, `routingMode=fast`,
   `alternatives=2`, `return=polyline,summary`, `departureTime` and `apiKey`.
   Vehicle dimensions are omitted: this validates HERE's default truck profile,
   not suitability for a specific loaded vehicle.
5. Expect one primary route and two alternatives. For every section inspect
   `polyline` (HERE Flexible Polyline), `summary.length` (metres), and
   `summary.duration` (seconds). The checker decodes geometry, validates points,
   sums all section distances/durations, and hashes decoded coordinates rounded
   to five decimals, eliminating consecutive duplicates. Three different IDs
   alone are insufficient. Pass requires three routes with three distinct
   geometry hashes. Different geometry does not mean entirely disjoint roads.
   Inspect saved section notices for warnings before treating a route as usable.

### Demo trip and reproducibility

**BLOCKED — no three-route demo is live verified without a HERE key.** The
following are candidates, not claims of successful routes:

1. Frankfurt am Main, Germany → Kassel, Germany.
2. Berlin, Germany → Hamburg, Germany.
3. Amsterdam, Netherlands → Rotterdam, Netherlands.

The search stops on the first three-route success. Default departure is **09:00
tomorrow in Europe/Berlin**, with the correct seasonal offset from IANA tzdata.
For the assessment date, this is `2026-11-25T09:00:00+01:00`. Amsterdam shares
that offset. Tomorrow falls inside the two-day weather request window. On a
later run, choose tomorrow again; do not reuse an expired forecast date.
The output records the exact departure, timezone, geocoded coordinates, route
parameters, full section polylines, distance/duration and geometry hashes.

To replay the first candidate with an explicit date:

```powershell
../.venv/Scripts/python.exe check_providers.py --provider here --origin "Frankfurt am Main, Germany" --destination "Kassel, Germany" --departure "2026-11-25T09:00:00+01:00" --timezone Europe/Berlin --output ../docs/testing/results/here-replay.json
```

After a successful search, substitute the winning origin/destination and exact
departure from the evidence. Record that winning pair and the result here before
declaring the demo verified. Traffic and map updates can change route availability;
the saved evidence is a snapshot, not a guarantee of future alternatives.

## Troubleshooting

- **Invalid credentials / 401 / 403:** verify the backend key and HERE application
  service access, subscription and key restrictions. Restart after changing app
  environment settings. Do not log full HERE URLs. The CLI reads `.env` per run.
- **429:** check quotas and retry later. Avoid repeated automated searches.
- **400:** inspect the documented coordinate, date/offset and routing parameters.
- **Fewer than three routes:** `alternatives=2` is a request, not a guarantee.
  Try the other documented corridors, or another explicit departure within the
  forecast window. Keep truck mode; do not duplicate a route, switch to car, or
  treat route IDs as distinct geometry. If all candidates fail, keep the demo
  unverified and record the attempt counts.
- **CORS:** frontend scheme, host and port must exactly match an allowed origin.
  `localhost` and `127.0.0.1` are different origins. Restart Django after changing
  `CORS_ALLOWED_ORIGINS`, and Vite after changing `VITE_API_BASE_URL`. A successful
  curl without an Origin header does not prove browser CORS works.
- **Connection refused:** confirm Django is listening on 8000 and the frontend
  URL points there. Health path includes a trailing slash. Check the browser's
  Network panel; CORS can obscure an underlying server error.
- **ENOSPC / Errno 28:** free disk space before reinstalling dependencies. Never
  interpret an incomplete installation as a code/test failure. Only delete this
  project's generated dependencies if a clean reinstall is needed.
- **Provider network failure:** check DNS, proxy, outbound HTTPS and certificates;
  the checker has a 30-second timeout and does not disable TLS verification.

## Verification record — 24 November 2026

Initial live Open-Meteo HTTP check passed: Frankfurt coordinates returned 48
records from `2026-11-24T00:00` through `2026-11-25T23:00`, expected units and
UTC offset zero. First wind value was 2.6 km/h; rain and snowfall were 0.

HERE geocoding, truck routing, route geometry/distance/duration and a reproducible
three-route demo: **BLOCKED by missing `HERE_API_KEY`**. Documentation review
is not a live provider check.

After freeing disk space and reinstalling incomplete dependencies:

- Frontend dependency installation and Vite production build: **PASSED**.
- Django system check: **PASSED**, no issues.
- Django health and allowed/denied CORS origin tests: **PASSED**, 2 tests.
- Live Django HTTP health request: **PASSED**, HTTP 200 and the expected
  `Access-Control-Allow-Origin` header for `http://127.0.0.1:5173`.
- Chromium/Playwright React-to-Django check: **PASSED**, 1 test. The rendered
  app displayed **Backend connected** on initial load and after a manual retry,
  using the actual backend across origins.
- Offline provider contract tests: **PASSED**, 3 tests covering multi-section
  totals, duplicate geometry rejection and credential-safe HTTP errors.
- Backend provider CLI: **Open-Meteo PASSED; HERE BLOCKED**, exit code 2.
  Sanitized local evidence: `docs/testing/results/providers.json` (gitignored).
- Git ignore checks: backend/frontend `.env` and generated provider evidence
  are ignored. No credentials were added to tracked source.

Initial installation failures were caused by a full C: drive, not test failures.

## References

- [HERE geocoding reference](https://docs.here.com/geocoding-and-search/reference/get_geocode)
- [HERE Routing v8 parameters and response](https://docs.here.com/routing/reference/routing-api-v8-calculateroutes)
- [HERE alternative routes](https://docs.here.com/routing/docs/routing-v8-get-alternative-routes)
- [HERE truck routing](https://docs.here.com/routing/docs/routing-v8-truck-routing)
- [HERE time-dependent routing](https://docs.here.com/routing/docs/routing-v8-time-dependent-routing)
- [HERE route geometry](https://docs.here.com/routing/docs/routing-v8-route-geometry)
- [Open-Meteo forecast fields, units and timestamps](https://open-meteo.com/en/docs)
