# senior-pomidor-server

Server implementation for the Senior Pomidor project.

## What It Runs

- `api`: FastAPI HTTP server on port `8000`.
- `worker`: MQTT subscriber for `senior-pomidor/+/telemetry`.
- `postgres`: persistent telemetry/photo metadata storage.
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

Compose has safe defaults, so a `.env` file is optional. To customize settings:

```powershell
Copy-Item .env.example .env
```

Start the services and apply migrations:

```powershell
docker compose up -d postgres mosquitto
docker compose run --rm api alembic upgrade head
docker compose up -d api worker
```

The API is available at `http://localhost:8000`, and the MQTT broker listens on `localhost:1883`.
Host port mappings can be changed with `API_PUBLISHED_PORT`, `POSTGRES_PUBLISHED_PORT`, `MQTT_PUBLISHED_PORT`, and `GRAFANA_PUBLISHED_PORT` in `.env`.

Start optional Grafana for local observability:

```powershell
docker compose --profile observability up -d grafana
```

Grafana is available at `http://localhost:3000`. The default local admin credentials are documented in `.env.example` and can be changed in `.env`.
Grafana uses the dedicated readonly PostgreSQL role from `GRAFANA_DB_USER` and `GRAFANA_DB_PASSWORD`, not the app database credentials.
The `Senior Pomidor Telemetry` dashboard is provisioned automatically and includes device/pod filters, telemetry panels, latest status, and recent photo metadata links.
The `Senior Pomidor Alerts` rule group is provisioned automatically and surfaces collection freshness, sensor error, system health, and critical dry-soil alerts in Grafana Alerting.
On a fresh `postgres_data` volume this role is initialized automatically. On an existing volume, re-apply the readonly grants after migrations:

```powershell
docker compose exec -T postgres sh /docker-entrypoint-initdb.d/20-grafana-reader.sh
```

For deployment checks, backups, restore, and Raspberry Pi configuration examples, see [docs/OPERATIONS.md](docs/OPERATIONS.md).
For 3/6/12 month hardware, storage, power, and 4/8/16 pod expansion estimates, see [docs/CAPACITY_PLANNING.md](docs/CAPACITY_PLANNING.md).

The offline AI analysis prototype for stored photos and telemetry is documented in
[docs/OPERATIONS.md](docs/OPERATIONS.md#offline-ai-analysis-prototype). It runs as a separate
CLI consumer and does not participate in API or MQTT ingestion.

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

HTTP telemetry ingestion is intentionally unauthenticated in v1 for compatibility with the current edge sender. Run the server on a trusted LAN and do not expose ingestion ports directly to the public internet.

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
- `GET /health`
- `GET /dashboard`

Telemetry may use schema `senior-pomidor.edge.telemetry.v1` or `senior-pomidor.edge.telemetry.v2`. Photos must use schema `senior-pomidor.edge.photo.v1` and upload a JPEG multipart field named `photo`.
