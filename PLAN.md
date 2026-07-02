# Senior Pomidor Core Server Specification

Historical note: this was the original v1 implementation plan. Current active contracts are documented in `docs/CONTRACTS.md`; this file is retained for project history and may describe constraints that have since changed, such as telemetry v2 support.

## Summary
Build a separate `senior-pomidor-server` repository for the first Core server version. The v1 server will run with Docker Compose on the home LAN, use **FastAPI + PostgreSQL**, receive telemetry from the Raspberry Pi edge node over MQTT first, accept HTTP telemetry as fallback, accept photo uploads over HTTP multipart, persist all received data, and expose read APIs for future dashboard/AI work.

The server must work with the current edge-node contract without requiring edge code changes.

## Architecture
- Create a separate repo from the edge node:
  - `api`: FastAPI HTTP API.
  - `worker`: MQTT subscriber process using the same application package.
  - `postgres`: persistent database.
  - `mosquitto`: local MQTT broker, unless an external broker is configured.
- Docker Compose services:
  - `api` listens on `0.0.0.0:8000`.
  - `worker` subscribes to MQTT topic pattern `senior-pomidor/+/telemetry`.
  - `postgres` stores telemetry, errors, photos, and raw payloads.
  - `mosquitto` exposes port `1883` on the LAN for the Raspberry Pi.
- Recommended edge config:
  - `MQTT_HOST=<server-lan-ip>`
  - `MQTT_PORT=1883`
  - `MQTT_TOPIC_PREFIX=senior-pomidor`
  - `HTTP_ENABLED=true`
  - `CORE_HTTP_URL=http://<server-lan-ip>:8000/api/v1/edge/telemetry`
  - `PHOTO_UPLOAD_ENABLED=true`
  - `PHOTO_UPLOAD_URL=http://<server-lan-ip>:8000/api/v1/edge/photos`

## Public Interfaces
- MQTT telemetry ingestion:
  - Subscribe to `{topic_prefix}/{device_id}/telemetry`, default `senior-pomidor/+/telemetry`.
  - Payload schema: `senior-pomidor.edge.telemetry.v1`.
  - QoS: support QoS 1.
  - Validate that topic `device_id` matches payload `device_id`; reject mismatches.
- HTTP telemetry fallback:
  - `POST /api/v1/edge/telemetry`
  - Body is the same JSON payload used for MQTT.
  - Must return `202 Accepted` after validation and persistence.
  - No required auth in v1, because the current edge HTTP sender does not send auth headers.
- HTTP photo upload:
  - `POST /api/v1/edge/photos`
  - Multipart file field: `photo`.
  - Form fields: `photo_id`, `device_id`, `captured_at_utc`, `schema_version`, `sharpness_score`.
  - Optional header: `Authorization: Bearer <PHOTO_UPLOAD_TOKEN>`.
  - Treat `photo_id` as an idempotency key; repeated uploads return `200 OK` or `202 Accepted` without duplicating storage.
- Read APIs:
  - `GET /api/v1/devices`
  - `GET /api/v1/devices/{device_id}/latest`
  - `GET /api/v1/devices/{device_id}/telemetry?from=&to=&pod=`
  - `GET /api/v1/devices/{device_id}/photos`
  - `GET /api/v1/photos/{photo_id}`

## Data Model
- `devices`
  - `device_id`, `first_seen_at`, `last_seen_at`, `last_payload_at`.
- `telemetry_events`
  - `id`, `device_id`, `timestamp_utc`, `schema_version`, `source`, `raw_payload_jsonb`, `received_at`.
  - Unique key: `device_id + timestamp_utc + schema_version`.
- `pod_readings`
  - `telemetry_event_id`, `device_id`, `pod_key`, `enabled`, metric columns for known v1 metrics, `metrics_jsonb`.
  - Known metrics: `adc_raw`, `soil_moisture_percent`, `soil_temperature_c`, `air_temperature_c`, `air_humidity_percent`, `air_pressure_hpa`, `light_lux`, `ir_ambient_temp_c`, `leaf_temp_c`.
- `pod_errors`
  - `telemetry_event_id`, `device_id`, `pod_key`, `sensor`, `message`.
- `photos`
  - `photo_id`, `device_id`, `captured_at_utc`, `schema_version`, `sharpness_score`, `content_type`, `file_size_bytes`, `storage_path`, `sha256`, `received_at`.
  - Unique key: `photo_id`.

## Validation And Behavior
- Accept only telemetry schema `senior-pomidor.edge.telemetry.v1`.
- Accept only photo schema `senior-pomidor.edge.photo.v1`.
- Validate timestamps as UTC ISO strings ending in `Z`.
- Preserve every accepted raw telemetry payload in `telemetry_events.raw_payload_jsonb`.
- Store known metric columns for querying, but keep unknown numeric metrics in `metrics_jsonb` for forward compatibility.
- Reject malformed telemetry with `400 Bad Request` on HTTP and log/reject on MQTT.
- Reject photo uploads that are not JPEG or exceed configured size limit; default max size: `25 MB`.
- Store photos on local disk in Docker volume `data/photos`, with DB metadata pointing to the file.
- MQTT is the primary ingestion path; HTTP telemetry is fallback only.

## Test Plan
- Unit tests for telemetry schema validation, timestamp parsing, topic-device matching, metric extraction, and disabled pods.
- Unit tests for photo form validation, idempotent `photo_id` handling, bearer-token behavior, and JPEG/content-size checks.
- Integration tests using FastAPI test client for:
  - `POST /api/v1/edge/telemetry`
  - `POST /api/v1/edge/photos`
  - latest telemetry read API
  - telemetry history read API
- Worker integration test with a local MQTT broker or test MQTT client publishing one valid edge payload.
- End-to-end local Docker test:
  - Start Compose.
  - Run edge node in mock mode with `MAX_TICKS=1`.
  - Confirm telemetry row exists.
  - Upload one test JPEG.
  - Confirm photo metadata and file are stored once after repeated upload.

## Assumptions
- Server lives in a separate repository.
- First version is ingestion + storage + read API only; dashboard and AI/VLM analysis are later layers.
- Deployment target is home LAN Docker Compose.
- Backend stack is FastAPI + PostgreSQL.
- HTTP telemetry remains unauthenticated in v1 for compatibility with the current edge sender; security is provided by LAN exposure and optional future edge-token support.
- Photo upload may require bearer auth because the current edge photo sender already supports `PHOTO_UPLOAD_TOKEN`.
