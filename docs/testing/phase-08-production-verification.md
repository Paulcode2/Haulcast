# Phase 8 — production deployment verification

## Scope

Harden Django for production, build the React frontend for production,
configure environment variables, verify Django production startup, deploy
via GitHub/hosting if possible, and document what remains blocked.

## Production hardening (done, committed in 909dba4 — push when network allows)

- `backend/config/settings.py`: env-driven production config —
  `DEBUG` from `DJANGO_DEBUG` (default false-safe), `ALLOWED_HOSTS` /
  `CORS_ALLOWED_ORIGINS` from env, `django.contrib.staticfiles` +
  WhiteNoise (`CompressedManifestStaticFilesStorage`, `STATIC_ROOT`),
  `CsrfViewMiddleware` + `XFrameOptionsMiddleware`,
  `SECURE_PROXY_SSL_HEADER` for TLS-terminating proxies,
  `SECURE_SSL_REDIRECT` / `SESSION_COOKIE_SECURE` / `CSRF_COOKIE_SECURE` /
  `SECURE_HSTS_*` / `CSRF_TRUSTED_ORIGINS` from env, console `LOGGING`.
- `backend/requirements.txt` + `backend/requirements.lock.txt`: added
  `gunicorn==23.0.0`, `whitenoise==6.12.0`, `packaging==26.4`.
- `backend/.env.example`: dev defaults incl. new production keys
  (all secure settings default off for local dev).
- `backend/.env.production.example`: full production template
  (secret generation command, hosts, CORS, HERE key, TLS/HSTS flags).
- `frontend/.env.example`: documents `VITE_API_BASE_URL` for production.
- `Procfile`: `web: gunicorn config.wsgi --chdir backend --bind
  0.0.0.0:$PORT --workers 3 --timeout 60 ...` (Heroku-style / Railway).
- `Dockerfile`: backend API container — `pip install -r
  backend/requirements.lock.txt`, `collectstatic`, gunicorn on `$PORT`.
- `render.yaml`: Render blueprint — `haulcast-api` (Docker, health check
  `/api/health/`) + `haulcast-app` (static `frontend/dist` with SPA
  rewrite). Placeholder hosts `haulcast-api.onrender.com` /
  `haulcast-app.onrender.com`; replace with real names before launching.
- `.github/workflows/ci.yml`: backend (`check --deploy` + 80 tests) and
  frontend (build + mocked e2e) on push/PR.
- `.gitignore` / `.dockerignore`: exclude venvs, `node_modules`,
  `frontend/dist`, `backend/staticfiles`, real `.env` files.

## Verification (local, 25 Nov 2026)

- `manage.py check` (dev env): **no issues**.
- `manage.py check --deploy` with full production-like env
  (`DEBUG=false`, 64-char secret, `ALLOWED_HOSTS=api.example.com`,
  `CORS=https://app.example.com`, SSL redirect + secure cookies,
  `HSTS=31536000` + subdomains + preload, CSRF trusted origin):
  **no issues** (partial envs still warn as expected, e.g. short dev
  secret or missing SSL redirect — all covered by the full-env pass).
- Backend tests: **80 passed** (`manage.py test api -v 1`; re-run after
  hardening: OK, system check clean).
- Frontend production build: **passed** (`npm --prefix frontend run
  build`; pre-existing >500 kB MapLibre chunk advisory only).
- `collectstatic`: **88 files post-processed** into
  `backend/staticfiles/` (WhiteNoise manifest storage OK).
- Production-mode boot (`DEBUG=false`, runserver on :8001, then stopped):
  `GET /api/health/` → 200 `{"status":"ok",...}`,
  `GET /static/rest_framework/css/bootstrap.min.css` → 200 (WhiteNoise),
  `POST /api/trips/analyze` with blank origin/destination → 400
  `validation_error` (validation path works with DEBUG off).
- WSGI import check in production env: `from config.wsgi import
  application` → callable OK.
- Gunicorn note: `gunicorn==23.0.0` is pinned in the lock file and used
  by `Procfile`/`Dockerfile`/CI image, but it cannot boot on this
  Windows box (`fcntl` missing — POSIX-only server). Production serving
  above was verified with Django + WhiteNoise; gunicorn runs on the
  Linux host/CI image. No gunicorn boot on Windows is claimed.

## Deploy steps (for the operator with hosting access)

1. Push `main` (committed as 909dba4; push when network allows).
2. Render (recommended): connect repo → `render blueprint launch` with
   `render.yaml`, set `HERE_API_KEY` (Geocoding & Search + Routing v8),
   confirm generated `DJANGO_SECRET_KEY`, replace placeholder hosts with
   the real `*.onrender.com` names in `DJANGO_ALLOWED_HOSTS`,
   `CORS_ALLOWED_ORIGINS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, and the
   frontend `VITE_API_BASE_URL` build arg.
   Alternatives: Railway (`Procfile` + Python build, set same env vars),
   Fly.io (`Dockerfile`, `fly launch` + secrets), Heroku
   (`Procfile`, `heroku config:set ...`).
3. Verify: `GET https://<api-host>/api/health/` → `{"status":"ok"}`;
   open the frontend, submit the demo trip, confirm 3 routes + map
   `data-ready=true` + checkpoint inspection.
4. Record the live URLs in README.md and below.

## Live demo

- **Status: NOT YET DEPLOYED — no live URL.**
- Blockers (all outside this repo):
  1. No hosting account / credentials available in this environment
     (Render/Railway/Fly/Heroku all need an operator login).
  2. Live routing needs a `HERE_API_KEY` with Geocoding & Search +
     Routing v8 set as a host env var (never committed). A key is
     present in local `backend/.env` for local runs; the host still
     needs its own value configured at deploy time.
  3. No `gh` CLI and no GitHub Actions run from here; CI workflow is
     committed but its first run happens on push.
- Everything deployable from code is done: harden → build → collectstatic
  → production-mode boot → health/static/validation checks all pass
  locally (see above).

## Deployed health check (run after deploy)

```powershell
curl.exe -sS https://<api-host>/api/health/
```

Expected HTTP 200:

```json
{"status": "ok", "service": "weather-aware-truck-routing"}
```

If the host path differs, use the Render health check path
`/api/health/` as configured in `render.yaml`.

## Expected route / forecast results (demo trip)

Demo trip: Frankfurt am Main, Germany → Kassel, Germany, tomorrow at
09:00 UTC, cargo 12,000 lb, interval 25 miles.

Live reference (Phase 7 smoke, real HERE + Open-Meteo, 25 Nov 2026):
3 distinct routes, 18/18 checkpoints complete, corridor 157 samples /
49 hours, ~1.27 MB response, `recommendation.status=recommended`
(duration tiebreak). Live counts vary with traffic, forecasts and road
availability — fewer than 3 routes is still success; the server never
invents alternatives.

Deterministic mocked reference (CI / `preview:mock`): 3 routes, fixed
checkpoints, corridor 3 points × 49 hours with hour 48 fully
`Unavailable`/`null`.

## Fresh-browser walkthrough (to run against the live URL)

1. Open the deployed frontend in a fresh profile (no cached env).
2. Click **Use demo trip** → **Analyze trip**.
3. Expect: 3 route cards (or fewer if HERE returns fewer), recommendation
   banner with explanation, map `data-ready=true`, route selection works
   both ways (card ↔ map line/R1-R3 button), checkpoint-2 dialog shows
   wind/rain/ETA/rule.
4. Scrub the forecast slider 0→24→48: route cards, selection,
   checkpoint ETAs and recommendation stay unchanged; hour-48 shows
   `Unavailable hour` (mocked) or real corridor data (live).
5. Submit **Analyze trip** again with slider at 24: slider resets to 0,
   stale heatmap replaced.

## Diagnosis: production API URL problems

- Symptom: frontend shows network/CORS/fetch failure, backend health is
  fine when curled directly.
- Cause: `VITE_API_BASE_URL` is baked at build time
  (`frontend/src/...`: `API_BASE = import.meta.env.VITE_API_BASE_URL`).
  Changing it requires a rebuild + redeploy of the static site.
- Fix: set `VITE_API_BASE_URL=https://<api-host>` (no trailing slash)
  in the frontend build environment (`render.yaml` build command does
  this), rebuild, redeploy, hard-refresh the browser. Verify in
  DevTools → Network that `POST` goes to the deployed host, not
  `localhost:8000`.

## Diagnosis: CORS problems

- Symptom: browser console `Access-Control-Allow-Origin` / CORS error on
  `POST /api/trips/analyze`; direct curl works.
- Cause: `CORS_ALLOWED_ORIGINS` must list the exact deployed frontend
  origin(s), scheme + host (+ port if non-standard), e.g.
  `https://haulcast-app.onrender.com`. A missing scheme, wrong host, or
  `http` vs `https` mismatch fails.
- Fix: set `CORS_ALLOWED_ORIGINS` on the API host to the exact frontend
  origin(s), restart/redeploy the API (env is read at startup), and
  confirm `DJANGO_ALLOWED_HOSTS` includes the API host. Local dev needs
  both localhost port-5173 forms; production must not rely on them.

## Diagnosis: provider credential problems

- `POST /api/trips/analyze` → 503 `provider_not_configured`: `HERE_API_KEY`
  is blank/unset on the host. Set it as a host env var/secret (Render:
  `sync: false` value; Railway/Fly/Heroku: secrets), restart, retry.
  Never commit the key or put it in `VITE_*`/frontend code.
- 502 `provider_error` with auth wording: 401 = invalid key, 403 =
  service not enabled for the key, 429 = quota/rate limit, 400 =
  invalid provider parameters. Fix on the HERE dashboard / key scope
  (needs Geocoding & Search + Routing v8 incl. truck), then retry.
- 502 `invalid_provider_response` / 504 `provider_timeout`: upstream or
  network issue, not config; retry, then check host egress/logs.
- Open-Meteo needs no key; missing/out-of-range hours are explicit
  `Unavailable`, never zero-filled.
