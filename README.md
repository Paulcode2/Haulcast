# Weather-Aware Truck Routing (Haulcast)

**For truck drivers and dispatchers:** enter where you're leaving from,
where you're headed, when, and how heavy your cargo is — and get up to
three truck routes compared by the weather you'll actually drive through,
not just by distance. Each route is broken into checkpoints every
10/25/50 miles with an estimated arrival time (ETA) at each one, the
forecast at that ETA, and a risk rating (Low … No Travel). The safest
route is recommended, and a corridor heatmap shows forecast risk along
the trip for the next 0–48 hours.

This document is the complete guide for anyone reviewing, running, or
deploying the project: architecture, data flow, risk rules, API contract,
local setup, testing, and deployment. A new developer should be able to
follow it end to end.

---

## 1. What the app does

1. The user enters **origin**, **destination**, **departure date/time**
   (with an explicit UTC offset), **cargo load weight (lb)**, and a
   **checkpoint interval** (10/25/50 miles; default 25).
2. The backend geocodes both places, requests up to **3 truck routes**
   from the HERE Routing API (never invents alternatives if HERE
   returns fewer), and samples each route at the requested interval —
   origin and destination are always included as checkpoints.
3. Every checkpoint gets an **ETA** (departure + routing durations,
   all UTC). For each ETA the backend pulls an **Open-Meteo** forecast
   (wind, rain, snowfall — no API key needed) and classifies a
   **weather risk level** from the thresholds in §4.
4. Routes are summarized by distance-weighted risk (§6) and ranked by
   the recommendation order in §7. Routes containing confirmed
   **No Travel** segments or incomplete forecast coverage are
   **excluded** from recommendation — the app never recommends an
   unsafe or unassessed route.
5. The frontend renders every route on an interactive **MapLibre** map:
   colored route lines, R1–R3 markers, numbered checkpoint markers,
   checkpoint detail popups, and a **forecast heatmap** along the trip
   corridor with a **0–48 hour slider** that recolors the corridor from
   already-loaded data (no extra requests while scrubbing).

---

## 2. Architecture

```
                ┌────────────────────────────────────────────┐
                │  Browser (React + Vite, MapLibre GL)       │
                │  frontend/src/main.jsx · TripMap.jsx      │
                │  planner.js (validation, formatting)       │
                └──────────────────┬─────────────────────────┘
                                   │  HTTPS / CORS
                                   │  POST /api/trips/analyze
                                   │  GET  /api/health/
                                   ▼
                ┌────────────────────────────────────────────┐
                │  Django + DRF (backend/)                   │
                │  api/views.py        → thin view layer     │
                │  api/serializers.py  → input validation    │
                │  api/providers.py    → HERE geocode+routes │
                │  api/weather.py      → Open-Meteo fetch    │
                │  api/risk.py         → risk thresholds     │
                │  api/routing.py      → checkpoints + ETAs  │
                │  api/ranking.py      → summaries + ranking │
                │  api/corridor.py     → heatmap data        │
                └───────┬───────────────┬────────────────────┘
                        │               │
                ┌───────▼──────┐ ┌──────▼─────────────────────┐
                │ HERE APIs    │ │ Open-Meteo (no key)      │
                │ geocode +    │ │ hourly forecast, UTC     │
                │ routing v8   │ └──────────────────────────┘
                │ truck mode   │
                └──────────────┘
```

Deployment split (see §9): the **frontend is a static site**
(Netlify or Render static), the **backend is a Docker/Gunicorn web
service** (Render/Railway/Fly/Heroku). The browser calls the backend
directly — there is no Vite proxy, so CORS is genuinely exercised.

---

## 3. API contract

### `GET /api/health/`

```json
{"status": "ok", "service": "weather-aware-truck-routing"}
```

### `POST /api/trips/analyze`

Request:

```json
{
  "origin": "Frankfurt am Main, Germany",
  "destination": "Kassel, Germany",
  "departure_time": "2026-11-26T09:00:00+01:00",
  "load_weight_lbs": 12000,
  "checkpoint_interval_miles": 25
}
```

`departure_time` must be ISO-8601 **with seconds and an explicit UTC
offset** (`...Z` or `...+HH:MM`); the frontend sends a fixed offset the
user picks, and the help text tells them DST is not applied
automatically.

Success (HTTP 200): origin/destination labels + coordinates,
`departure_time`, `load_weight_lbs` (`weight_semantics: "cargo_only" —
cargo is separate from gross vehicle weight`), `checkpoint_interval_miles`,
`weather_coverage`, `recommended_route_id` (nullable),
`recommendation`, `corridor_forecast`, `route_count`, and `routes[]`.
Each route has `distance_miles`, `duration_seconds`,
`destination_eta`, GeoJSON `geometry`, `checkpoints[]` (distance, ETA,
weather values + coverage, risk level + triggering rule), and a
`summary` (see §6).

Errors are structured, never bare HTTP pages:

| Status | Code | Meaning |
| ------ | ---- | ------- |
| 400 | `validation_error` | Field-level `error.fields` messages shown inline in the form |
| 422 | `geocoding_not_found` | A location couldn't be geocoded |
| 422 | `no_routes` | HERE returned zero truck routes |
| 503 | `provider_not_configured` | `HERE_API_KEY` missing on the host |
| 502 / 504 | `provider_error`, `invalid_provider_response`, `provider_timeout` | Upstream HERE failure (401 = bad key, 403 = service not enabled, 429 = quota) |

Provider error bodies and keyed URLs are **never** returned to the
client or printed in logs — see `providers.py`.

All downstream statuses are deliberate: if *no* route is eligible, the
API still returns HTTP 200 with all routes plus `recommended_route_id:
null` and `recommendation.status: "no_recommendation"`. It never
falls back to recommending an unsafe route.

---

## 4. Risk rules (`backend/api/risk.py`)

`classify_risk(wind_mph, rain_in_per_hour, snow_in_per_hour,
load_weight_lbs)` is a pure function. Each field is rated separately
and the **highest single-field rating wins**; the `reasons` array names
every field tied at that top rating, so the UI can quote the exact
rule that fired.

**Wind (mph):** <25 Low · 25–34 Moderate · 35–44 High · 45–54 Severe ·
≥55 No Travel.

**Rain (in/hr, preceding-hour total ÷ 1 h):** <0.10 Low · 0.10–0.25
Moderate · 0.25–0.50 High · 0.50–1.00 Severe · **>1.00** No Travel
(exactly 1.00 stays Severe).

**Snow (in/hr water-rate from cm depth):** <0.5 Low · 0.5–1.0 Moderate ·
1.0–2.0 High · 2.0–3.0 Severe · **>3.0** No Travel (exactly 3.0 stays
Severe).

**Cargo overrides** (strict `>` on weight):

- Wind **45–<55 mph** with cargo **>30,000 lb** → **No Travel**
- Wind **35–<45 mph** with cargo **>40,000 lb** → **Severe**

**Missing/invalid data** (null, NaN, negative, bool): the field is
skipped and listed in `missing_fields`; `coverage_complete=false` and
`assessment_status=incomplete` — *unless* a confirmed No Travel
already holds, in which case `assessment_status=confirmed` (a known
maximum survives missing weather). All fields missing → `Unknown`.
The app never zero-fills and never reuses a nearby forecast hour.

---

## 5. ETA assumptions (`backend/api/routing.py`)

- Checkpoints are sampled along the decoded polyline geometry by
  haversine distance (R = 6,371,008.8 m; 1 mi = 1,609.344 m) — not
  straight-line, nominal-interval, or HERE road-network totals.
  (Both geometry miles and provider miles are returned; ranking uses
  geometry miles at 6-decimal precision.)
- Origin + destination are always included; interior checkpoints
  fall every 10/25/50 mi. An endpoint within 0.1 m of an interval
  appears once; a short final segment is kept (e.g. 0/25/50/67 for a
  67-mile route).
- Timing spreads each HERE section's summary duration by its span
  weights (span durations weight geometry distance inside the span);
  unlocated pre/post-action time spreads proportionally. Invalid or
  absent spans fall back to distance interpolation within the section.
  `timing_methods` in the response exposes which path applied per
  checkpoint.
- `destination_eta` = departure + `duration_seconds`; the final
  checkpoint ETA equals it exactly. All ETAs are UTC ISO-8601. These
  are **estimated travel ETAs**, not a stop/waiting schedule.
- **Forecast pairing:** wind uses the nearest forecast hour (later
  hour on a :30 tie); rain/snow use the interval `(t−1h, t]` containing
  the ETA, as precipitation accumulations.

---

## 6. Segment risk method (`backend/api/ranking.py`)

Ranking never uses rounded display miles. Per consecutive checkpoint
pair, the segment length comes from unrounded cumulative
`distance_meters`:

1. Both endpoints complete + known → the **higher endpoint rating**
   wins the segment.
2. Either endpoint is confirmed **No Travel** → segment is No Travel
   (even beside an Unknown/incomplete endpoint).
3. Otherwise any incomplete coverage → **Unknown** (a partial
   endpoint's best rating is not final — missing weather could raise
   it).

`average_risk = Σ(segment_mi × score) / Σ(segment_mi)` with
Low 0 / Moderate 1 / High 2 / Severe 3 / No Travel 4; it is `null`
if any segment is Unknown (unknown miles are never zeroed or dropped,
so a route with unassessed weather can't look artificially safe).
`severe_miles` / `high_miles` / `no_travel_miles` count miles at
exactly that rating. `unknown_coverage_miles` covers segments
adjoining incomplete checkpoints and **may overlap** No Travel miles —
do not sum the counters as a partition. Display rounding
(`summary.display`, 2 decimals) is presentation-only; ranking uses
raw floats.

---

## 7. Recommendation exclusions & order (`backend/api/ranking.py`)

A route is **excluded** when either holds (both are reported when
both hold):

- `no_travel_segments` — ≥1 No Travel segment.
- `incomplete_forecast_coverage` — ≥1 checkpoint without full
  forecast coverage.

Eligible routes compare **lexicographically on raw values**:

1. Fewest **Severe** miles
2. Fewest **High** miles
3. Lowest **average risk**
4. Shortest `duration_seconds`

An exact tie on all four keeps provider order
(`deciding_factor: "exact_tie"`); a single eligible route reports
`deciding_factor: "only_eligible_route"`. The response explains which
criterion decided the comparison against the runner-up.

---

## 8. Corridor heatmap & forecast slider

- `corridor_forecast` carries sampled points (≤250) along the
  recommended corridor with lateral ±6 mi offsets and **49 hourly
  values per point** (hour 0–48, floored UTC-hour reference).
- The frontend **Forecast hour slider** (0–48) only recolors the
  corridor heat dots from that already-loaded payload — **scrubbing
  issues no requests** and leaves geometry, selection, ETAs, route
  cards, and the recommendation unchanged.
- Missing hours are explicit `Unavailable`/gray, never interpolated.
  A new analysis resets the slider to 0 and replaces stale heat data.

---

## 9. Local setup

**Requirements:** Python 3.12+ (3.14 used here), Node.js 22.12+
(24.14 used here), npm, internet access.

```powershell
# Windows PowerShell (repo root)
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r backend/requirements.lock.txt
Copy-Item backend/.env.example backend/.env
Copy-Item frontend/.env.example frontend/.env
cd frontend
npm.cmd ci
cd ..
```

Do not overwrite an existing `.env` on repeat setup. On macOS/Linux use
`python3`, `.venv/bin/python`, `cp`, `npm`. On Windows use `npm.cmd`
(avoids the `npm.ps1` execution-policy restriction).

**Run** (two terminals, repo root):

```powershell
./.venv/Scripts/python.exe backend/manage.py runserver 127.0.0.1:8000 --noreload
```

```powershell
cd frontend
npm.cmd run dev
```

Open `http://127.0.0.1:5173` → expect **Backend connected**. No Vite
proxy: the browser calls Django directly, exercising CORS.

### Environment variables

| Variable | File | Purpose / default |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | `backend/.env` | Required Django secret; example is dev-only. Generate: `python -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `DJANGO_DEBUG` | `backend/.env` | `true` locally; production `false` |
| `DJANGO_ALLOWED_HOSTS` | `backend/.env` | Comma-separated hosts; default `localhost,127.0.0.1` |
| `CORS_ALLOWED_ORIGINS` | `backend/.env` | Exact frontend origins; default both localhost `:5173` forms |
| `HERE_API_KEY` | `backend/.env` | Backend-only HERE key (enable **Geocoding & Search** + **Routing v8** incl. truck on the key); blank = live routing disabled |
| `VITE_API_BASE_URL` | `frontend/.env` | Public Django origin; default `http://127.0.0.1:8000` |
| `DJANGO_SECURE_SSL_REDIRECT` | prod env | `true` behind HTTPS |
| `DJANGO_SESSION_COOKIE_SECURE` / `DJANGO_CSRF_COOKIE_SECURE` | prod env | `true` behind HTTPS |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | prod env | `https://<frontend-host>` |
| `DJANGO_SECURE_HSTS_SECONDS` (+ subdomains/preload) | prod env | e.g. `31536000` once fully HTTPS |
| `DJANGO_LOG_LEVEL` | both | Default `INFO` |

Process env wins over `.env`. Never put a HERE key in `VITE_*`,
frontend source, shell history, or screenshots. Production template:
`backend/.env.production.example`. **Never commit a filled-in `.env`**
(the `.gitignore` excludes `.env*` except the templates).

---

## 10. Testing

### Backend (repo root, Windows paths)

```powershell
./.venv/Scripts/python.exe backend/manage.py check
./.venv/Scripts/python.exe backend/manage.py check --deploy   # production-like env
./.venv/Scripts/python.exe backend/manage.py test api -v 1    # full backend suite
```

Phase 1 provider checker (from `backend/`):

```powershell
../.venv/Scripts/python.exe -m unittest test_providers -v
```

### Frontend (from `frontend/`, Django running for the health check)

```powershell
npm.cmd run build
npm.cmd run test:e2e -- tests/planner.spec.js
npm.cmd run test:e2e
```

Default e2e is mocked/offline (Playwright intercepts API calls);
`tests/live-trip.spec.js` needs `RUN_LIVE_TRIP=1` plus a valid backend
key. CI (`.github/workflows/ci.yml`) runs backend checks + tests and
the frontend build + mocked e2e on every push/PR.

### Demo trip

Click **Use demo trip** → **Analyze trip**:

- Frankfurt am Main, Germany → Kassel, Germany; tomorrow 09:00 UTC;
  cargo 12,000 lb; interval 25 miles.
- Expect: route cards with distance/duration/destination ETA,
  Severe/High/No-Travel/unknown miles, average score, eligibility or
  exclusion reasons; recommendation banner with explanation; fitted
  map with `data-ready=true`; click card ↔ map line/R1–R3 selects both
  ways; checkpoint dialog shows wind/rain/ETA/rule.
- Scrub **Forecast hour** 0→24→48: heat dots recolor from loaded data
  only (one analysis request total); cards, selection, ETAs,
  recommendation unchanged; hour 48 in the mocked run shows
  `Unavailable hour` with gray dots.
- Live reference (25 Nov 2026): 3 routes, 18/18 checkpoints complete.
  HERE may legitimately return fewer than 3 — still success; the
  server never invents alternatives.

---

## 11. Deployment

### 11.1 Backend (Docker on Render — current setup)

[Dockerfile](Dockerfile) builds the image: install
`backend/requirements.lock.txt`, `collectstatic` (with a build-time-only
dummy secret — the real `DJANGO_SECRET_KEY` is a runtime env var), serve
with Gunicorn on `$PORT`. Health check: `/api/health/`.

Render → **New Web Service → Docker**, Dockerfile Path `./Dockerfile`,
no build/start command needed. Required environment variables:

```
DJANGO_SECRET_KEY=<generate — see §9>
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=<your-api-host>.onrender.com
CORS_ALLOWED_ORIGINS=https://<your-frontend-host>
DJANGO_CSRF_TRUSTED_ORIGINS=https://<your-frontend-host>
HERE_API_KEY=<HERE key — Geocoding & Search + Routing v8>
DJANGO_SECURE_SSL_REDIRECT=true
DJANGO_SESSION_COOKIE_SECURE=true
DJANGO_CSRF_COOKIE_SECURE=true
DJANGO_SECURE_HSTS_SECONDS=31536000
DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=true
DJANGO_SECURE_HSTS_PRELOAD=true
```

> The committed [render.yaml](render.yaml) blueprint contains
> placeholder hosts (`haulcast-api.onrender.com`). If you used the
> blueprint, **override `DJANGO_ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`,
> `DJANGO_CSRF_TRUSTED_ORIGINS`, and the frontend `VITE_API_BASE_URL`
> in the Render dashboard** with the real hostnames you were assigned
> (they look like `haulcast-p76u.onrender.com`).

Verify: `GET https://<api-host>/api/health/` → `{"status":"ok",...}`.

**Non-Docker alternative:** `pip install -r backend/requirements.lock.txt`,
`collectstatic`, then from `backend/`:
`gunicorn config.wsgi --bind 0.0.0.0:$PORT --workers 3 --timeout 60`
(the root [Procfile](Procfile) wraps this for Heroku/Railway).

### 11.2 Frontend (Netlify static site)

1. Netlify → **Add new site → Import an existing project** → connect
   the GitHub repo.
2. Build settings:

   | Setting | Value |
   | --- | --- |
   | **Base directory** | `frontend` |
   | **Build command** | `npm run build` |
   | **Publish directory** | `dist` |

3. Environment variable (set **before** the first deploy — it is baked
   in at build time):

   ```
   VITE_API_BASE_URL=https://<your-api-host>.onrender.com
   ```

4. **Deploy site.** Add a SPA redirect so refreshes on any route serve
   `index.html`: create `frontend/public/_redirects` containing
   `/*  /index.html  200`.
5. Once Netlify gives you a URL, update the backend's
   `CORS_ALLOWED_ORIGINS` and `DJANGO_CSRF_TRUSTED_ORIGINS` to that
   exact origin (scheme + host) and redeploy the API.

> **Changing `VITE_API_BASE_URL` requires a rebuild + redeploy** of
> the static site — the value is compiled into the JS bundle.

### 11.3 Troubleshooting (the two failures everyone hits)

- **`DisallowedHost` / HTTP 400 on every API call** (health check
  included): the `Host` header isn't in `ALLOWED_HOSTS`. Fix
  `DJANGO_ALLOWED_HOSTS` on the API host to the exact hostname Render
  assigned you, then redeploy.
- **CORS error in the browser console** (curl works, browser fails):
  `CORS_ALLOWED_ORIGINS` must list the exact deployed frontend origin
  (scheme + host). A missing scheme, wrong host, or `http` vs `https`
  mismatch fails. Fix on the API host, redeploy (env is read at
  startup).
- **`503 provider_not_configured`**: `HERE_API_KEY` missing on the
  host — set it as a host env var/secret, restart, retry.
- **MapLibre `Worker failed to load`**: the Vite worker must be
  explicit — `worker: { format: 'es' }` in `vite.config.js` plus
  `maplibregl.setWorkerUrl(...)` in `TripMap.jsx:3-4` imports
  `maplibre-gl/dist/maplibre-gl-worker.mjs?url`.

---

## 12. Repository layout

```
.
├── Dockerfile                  # backend container (Render/Railway/Fly)
├── Procfile                    # gunicorn web process (Heroku/Railway)
├── render.yaml                 # Render blueprint (placeholder hosts)
├── README.md                   # this file
├── .github/workflows/ci.yml    # backend checks+tests, frontend build+e2e
├── backend/
│   ├── manage.py
│   ├── check_providers.py      # Phase 1 live provider checker (dev tool)
│   ├── requirements.txt        # direct deps (ranges)
│   ├── requirements.lock.txt   # pinned lock (Docker/CI install this)
│   ├── .env.example            # dev env template
│   ├── .env.production.example # production env template
│   ├── config/                 # settings, urls, wsgi
│   └── api/                    # the whole feature
│       ├── views.py            # health + analyze_trip views
│       ├── serializers.py      # input validation
│       ├── providers.py        # HERE geocoding + routing adapter
│       ├── weather.py          # Open-Meteo forecast adapter
│       ├── risk.py             # risk thresholds (§4)
│       ├── routing.py          # checkpoint sampling + ETAs (§5)
│       ├── ranking.py          # segments, summaries, recommendation (§6–7)
│       ├── corridor.py         # corridor heatmap payload (§8)
│       └── test_*.py, tests.py # backend test suite
├── frontend/
│   ├── package.json / package-lock.json
│   ├── vite.config.js          # worker format + chunk naming
│   ├── .env.example            # VITE_API_BASE_URL template
│   ├── index.html
│   ├── src/
│   │   ├── main.jsx            # App: form, submission, results
│   │   ├── TripMap.jsx         # MapLibre map + heatmap + slider UI
│   │   ├── planner.js          # validation + formatting helpers
│   │   └── style.css
│   └── tests/                  # Playwright e2e (mocked; live opt-in)
└── docs/testing/               # phase-by-phase verification notes
    └── phase-01 … phase-08     # setup → providers → routes → weather
                                # → ranking → planner → heatmap →
                                # regression → production verification
```

## 13. Status

- **Repo:** `Paulcode2/Haulcast`, branch `main`, CI green on push/PR.
- **Live URLs:** backend on Render (`haulcast-p76u.onrender.com`),
  frontend on Netlify — record them here once both verify (§11.3).
- **Known approximation:** segment risk attributes the worse endpoint
  rating to the whole segment; rain/snow are interval accumulations;
  corridor heat uses lateral offsets. All are documented in §4–§8 and
  exposed in the response (`timing_methods`, coverage flags) rather
  than hidden.
