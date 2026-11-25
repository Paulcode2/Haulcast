# Phase 8 — production deployment verification

## Scope

Harden Django for production, build the React frontend for production,
configure environment variables, verify Django production startup, deploy
via GitHub/hosting if possible, and document what remains blocked.

## Production hardening (done, staged — push when network allows)

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
  rewrite). Fill in `HERE_API_KEY` and real hosts before launching.
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
  Linux host/CI image.

## Deploy steps (for the operator with hosting access)

1. Push `main` (this phase is staged; push when network allows).
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
  2. `HERE_API_KEY` is empty in `backend/.env` — live routing needs a
     key with Geocoding & Search + Routing v8 enabled.
  3. No `gh` CLI and no GitHub Actions run from here; CI workflow is
     committed but its first run happens on push.
- Everything deployable from code is done: harden → build → collectstatic
  → production-mode boot → health/static/validation checks all pass
  locally (see above).

## Fresh-browser walkthrough (to run against the live URL)

1. Open the deployed frontend in a fresh profile (no cached env).
2. Click **Use demo trip** → **Analyze trip**.
3. Expect: 3 route cards, recommendation shown, map `data-ready=true`,
   route selection both ways, checkpoint-2 dialog with wind/rain/ETA/rule.
4. Scrub the forecast slider 0→24→48: selection unchanged, hour-48 shows
   `Unavailable hour` (mocked) or real corridor data (live).
