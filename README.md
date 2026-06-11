# senior-pomidor-server

Server implementation for the Senior Pomidor project.

## What It Runs

- `api`: FastAPI HTTP server on port `8000`.
- `worker`: MQTT subscriber for `senior-pomidor/+/telemetry`.
- `postgres`: persistent telemetry/photo metadata storage.
- `mosquitto`: local MQTT broker exposed on port `1883`.

The server accepts the current edge-node telemetry contract without requiring edge code changes.

## Local Python Setup

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q
```

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

For deployment checks, backups, restore, and Raspberry Pi configuration examples, see [docs/OPERATIONS.md](docs/OPERATIONS.md).

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
