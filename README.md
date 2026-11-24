# Weather-Aware Truck Routing

React + Vite, Django REST Framework, local CORS, backend-only HERE provider
integration, and trip routes with distance checkpoints and estimated arrival times.
Checkpoints include ETA-matched Open-Meteo forecasts and weather/load risk levels.
Route ranking and the weather frontend workflow are not implemented.

See [setup and provider verification](docs/testing/phase-01-setup-and-providers.md)
for installation, environment configuration, run commands, evidence and blockers.

See [Phase 2 route API and tests](docs/testing/phase-02-routes-checkpoints-and-etas.md)
for `POST /api/trips/analyze`, validation, checkpoint intervals and ETA semantics.

See [Phase 3 weather and risk tests](docs/testing/phase-03-weather-and-checkpoint-risk.md)
for forecast selection, unit conversions, coverage and pure risk rules.
