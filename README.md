# Weather-Aware Truck Routing

React + Vite, Django REST Framework, local CORS, backend-only HERE provider
integration, and trip routes with distance checkpoints and estimated arrival times.
Checkpoints include ETA-matched Open-Meteo forecasts and weather/load risk levels.
Routes include distance-weighted risk summaries and an eligibility-filtered
recommendation. The React planner includes an interactive route map, route
selection, checkpoint weather inspection and responsive result cards.

See [setup and provider verification](docs/testing/phase-01-setup-and-providers.md)
for installation, environment configuration, run commands, evidence and blockers.

See [Phase 2 route API and tests](docs/testing/phase-02-routes-checkpoints-and-etas.md)
for `POST /api/trips/analyze`, validation, checkpoint intervals and ETA semantics.

See [Phase 3 weather and risk tests](docs/testing/phase-03-weather-and-checkpoint-risk.md)
for forecast selection, unit conversions, coverage and pure risk rules.

See [Phase 4 route ranking](docs/testing/phase-04-route-ranking.md) for segment
summaries, exclusions, recommendation criteria and deterministic fixtures.

See [Phase 5 planner and map](docs/testing/phase-05-trip-planner-and-map.md) for
startup, browser walkthroughs, mock scenarios and live frontend verification.
