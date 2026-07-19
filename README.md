# senior-pomidor-server

Server implementation for the Senior Pomidor project.

## What It Runs

- `api`: FastAPI HTTP server on port `8000`.
- `worker`: MQTT subscriber for `senior-pomidor/+/telemetry`.
- `state-estimator-worker`: recurring canonical state, sensor health, anomaly, diagnostic, and private JSONL writer.
- `postgres`: local-development telemetry/photo metadata storage (platform-managed in production).
- `mosquitto`: local MQTT broker exposed on port `1883`.
- `grafana`: optional local observability UI exposed on port `3000`.

The server accepts the current edge-node telemetry contract without requiring edge code changes.

## Local Python Setup

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q
```

Run the full local quality harness:

```powershell
nox -s tests lint format_check types security deps_audit
```

Install pre-commit hooks for fast local feedback:

```powershell
pre-commit install
pre-commit run --all-files
```

CI treats tests, linting, format checks, type checks, security checks, dependency
audits, and Docker vulnerability scans as blocking gates.

Docker Compose end-to-end coverage is opt-in because it requires Docker and uses local ports:

```powershell
$env:RUN_DOCKER_E2E='1'
python -m pytest -q tests/test_docker_e2e.py
Remove-Item Env:RUN_DOCKER_E2E
```

For an ad hoc SQLite-backed API run:

```powershell
uvicorn app.main:app --reload
```

## Docker Compose

The base Compose file contains only application-owned services. Local development adds PostgreSQL,
Grafana, Ollama, and build configuration with `docker-compose.dev.yml`; production instead uses
`docker-compose.prod.yml` to join independently managed platform services. Copy the local environment
template first:

```powershell
Copy-Item .env.example .env
```

Start the services. The one-shot `migrate` service applies Alembic migrations before the API, MQTT worker, and state estimator worker start:

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

The API is available at `http://localhost:8000`, and the MQTT broker listens on `localhost:1883`.
The state estimator runs continuously in Compose by default. It writes canonical `state_v1` snapshots, sensor health, anomalies, diagnostics, and private JSONL logs under the configured bind-mount directory.
Host port mappings can be changed with `API_PUBLISHED_PORT`, `POSTGRES_PUBLISHED_PORT`, `MQTT_PUBLISHED_PORT`, and `GRAFANA_PUBLISHED_PORT` in `.env`. `LAN_BIND_ADDRESS` limits API, MQTT, and Grafana to one trusted interface; PostgreSQL defaults to host-only through `POSTGRES_BIND_ADDRESS=127.0.0.1`.
Published API, MQTT, and optional Grafana ports are intended for trusted LAN use only. Do not expose them directly to the public internet; put remote access behind a VPN or a hardened reverse proxy/firewall.
For appliance-like deployments, set non-default PostgreSQL and Grafana credentials, configure `TELEMETRY_UPLOAD_TOKEN` and `PHOTO_UPLOAD_TOKEN`, and set `API_DOCS_ENABLED=false`.
Use `GET /health` for shallow liveness and `GET /ready` for database plus migration readiness.

Start optional Grafana for local observability:

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile observability up -d grafana
```

Grafana is available at `http://localhost:3000`. The default local admin credentials are documented in `.env.example` and can be changed in `.env`.
Grafana uses the dedicated readonly PostgreSQL role from `GRAFANA_DB_USER` and `GRAFANA_DB_PASSWORD`, not the app database credentials.
The `Senior Pomidor Telemetry` dashboard is provisioned automatically and includes device/pod filters, raw telemetry panels, canonical state panels, latest sensor health, active anomalies, latest status, and recent photo metadata links.
The `Senior Pomidor Alerts` rule group is provisioned automatically and surfaces collection freshness, sensor error, system health, critical dry-soil, raw telemetry VPD, canonical state VPD, state confidence, active anomaly, and stale state alerts in Grafana Alerting. VPD ranges are documented in [docs/VPD_ALERTS.md](docs/VPD_ALERTS.md).
On a fresh PostgreSQL data directory this role is initialized automatically. On an existing directory, re-apply the readonly grants after migrations:

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec -T postgres sh /docker-entrypoint-initdb.d/20-grafana-reader.sh
```

## Grafana Cloud Public Metrics Export

Grafana Cloud export is optional and disabled by default. It reads local PostgreSQL telemetry and sends a read-only public projection to Grafana Cloud Metrics with Prometheus remote write:

```powershell
GRAFANA_CLOUD_EXPORT_ENABLED=true
GRAFANA_CLOUD_REMOTE_WRITE_URL=<remote-write-url>
GRAFANA_CLOUD_INSTANCE_ID=<instance-id>
GRAFANA_CLOUD_API_TOKEN=<metrics-publisher-token>
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile cloud-export up -d grafana-cloud-exporter
```

Only low-cardinality raw telemetry plant metrics are exported, using metric names prefixed with `senior_pomidor_` and labels limited to `device_id` and `pod_key`. Canonical state estimator metrics are not exported to Grafana Cloud in this iteration. Photos, raw payload JSON, system health, sensor error text, host/network details, database credentials, file paths, and MQTT topics are not exported. Grafana Cloud is a public read-only projection; PostgreSQL remains the local source of truth.

For active API/edge contracts and example requests/responses, see [docs/CONTRACTS.md](docs/CONTRACTS.md).
For deployment checks, backups, restore, and Raspberry Pi configuration examples, see [docs/OPERATIONS.md](docs/OPERATIONS.md).
For the immutable Ubuntu production layout, see [docs/UBUNTU_HOST.md](docs/UBUNTU_HOST.md), and for the cold cutover see [docs/MIGRATION_WINDOWS_TO_UBUNTU.md](docs/MIGRATION_WINDOWS_TO_UBUNTU.md).
For step-by-step Raspberry Pi integration, see [docs/PI_INTEGRATION_RUNBOOK.md](docs/PI_INTEGRATION_RUNBOOK.md).
For 3/6/12 month hardware, storage, power, and 4/8/16 pod expansion estimates, see [docs/CAPACITY_PLANNING.md](docs/CAPACITY_PLANNING.md).
For release notes, see [CHANGELOG.md](CHANGELOG.md).

The offline AI analysis prototype for stored photos and telemetry is documented in
[docs/OPERATIONS.md](docs/OPERATIONS.md#offline-ai-analysis-prototype). It runs as a separate
CLI consumer and does not participate in API or MQTT ingestion.

## Optional Daily Tomato Story

The `daily-story` Compose profile runs a local CPU-only Ollama service, pulls the configured model into the persistent
`ollama_models` volume, and starts a daily story worker after migrations and model bootstrap complete:

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile daily-story up -d
```

The normal Compose stack is unchanged when the profile is not selected. Ollama is published only on
`127.0.0.1:11434` by default. Override `OLLAMA_IMAGE` through a deployment-specific Compose override if GPU support
is required; application code uses the same HTTP API.

The worker generates at most one story for `DAILY_STORY_NODE_ID` per local calendar date. It uses the configured
`DAILY_STORY_SCHEDULE_TIME` and `DAILY_STORY_TIMEZONE`, summarizes the preceding
`DAILY_STORY_LOOKBACK_HOURS` without sending raw database rows, and never backfills an older local date. A restart
after today's due time resumes only today's record. No telemetry produces a persisted `skipped_no_data` result and
does not call Ollama.

Defaults and the complete configuration contract are in [.env.example](.env.example). Important settings include
poll/retry/stale limits, prompt paths, context sizes, memory depth, Ollama host/model/timeout/keep-alive, and the seeded bounded
`DAILY_STORY_OLLAMA_OPTIONS_JSON`. Default prompt files are in `config/daily_story/`; the worker fails startup if
either file is missing or the user template omits any required token: `{{NODE_ID}}`, `{{WINDOW_START_UTC}}`,
`{{WINDOW_END_UTC}}`, `{{ENVIRONMENT_CONTEXT_JSON}}`, or `{{CONTEXT_JSON}}`.

`config/daily_story/environment.json` supplies non-telemetry facts such as identity, species, location, germination,
pot and soil details, growth stage, flowers, fruits, neighboring plants, life events, and writing preferences. Its
`running_memories.notes` are operator-maintained. For each run, the worker also adds up to
`DAILY_STORY_MEMORY_ENTRIES` previous successful diary entries for the same node. This environment layer is bounded,
stored privately with the run, and excluded from the public API. `DAILY_STORY_OLLAMA_KEEP_ALIVE=0` releases model
memory after generation.

Worker health is written to its container health file. Waiting, succeeded, and skipped states are healthy; a failed
state makes the container health check fail while the worker retains the bounded error privately for retry and
operations review.

Before enabling this profile in a deployment, complete the mandatory seeded generation and API retrieval procedure
in [docs/OPERATIONS.md](docs/OPERATIONS.md#mandatory-daily-story-manual-acceptance-test). This real-model test is an
operator acceptance gate and is intentionally not part of the automated test suite.

## Edge Configuration

Use the server LAN IP for the Raspberry Pi:

```text
MQTT_HOST=<server-lan-ip>
MQTT_PORT=1883
MQTT_TOPIC_PREFIX=senior-pomidor
HTTP_ENABLED=true
CORE_HTTP_URL=http://<server-lan-ip>:8000/api/v1/edge/telemetry
PHOTO_UPLOAD_ENABLED=true
PHOTO_UPLOAD_URL=http://<server-lan-ip>:8000/api/v1/edge/photos
```

If `PHOTO_UPLOAD_TOKEN` is set on the server, the edge photo uploader must send it as a bearer token.
If `TELEMETRY_UPLOAD_TOKEN` is set on the server, HTTP telemetry ingestion must also send `Authorization: Bearer <token>`.

HTTP telemetry ingestion and photo upload remain unauthenticated by default unless their bearer-token environment variables are configured. This default is for compatibility with current trusted-LAN edge senders only. Set `API_DOCS_ENABLED=false` for production-like appliance deployments to disable `/docs`, `/redoc`, and `/openapi.json`. The built-in `/dashboard` is a LAN convenience view and is not designed as a public internet dashboard.

## HTTP API

- `POST /api/v1/edge/telemetry`
- `POST /api/v1/edge/photos`
- `GET /api/v1/devices`
- `GET /api/v1/devices/latest`
- `GET /api/v1/devices/{device_id}/latest`
- `GET /api/v1/devices/{device_id}/telemetry?from=&to=&since_hours=&pod=&limit=`
- `GET /api/v1/devices/{device_id}/photos?from=&to=&limit=`
- `GET /api/v1/photos/recent?from=&to=&limit=`
- `GET /api/v1/photos/{photo_id}`
- `GET /api/v1/state/latest?node_id=`
- `GET /api/v1/sensor-health/latest?node_id=`
- `GET /api/v1/anomalies/active?node_id=`
- `GET /api/v1/daily-stories/latest?node_id=`
- `GET /api/v1/daily-stories/range?node_id=&from=&to=&limit=`
- `GET /health`
- `GET /ready`
- `GET /dashboard`

Telemetry may use schema `senior-pomidor.edge.telemetry.v1` or `senior-pomidor.edge.telemetry.v2`. Photos must use schema `senior-pomidor.edge.photo.v1` and upload a JPEG multipart field named `photo`.
