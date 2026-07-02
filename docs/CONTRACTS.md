# Senior Pomidor Active Server Contracts

This document describes the contracts implemented by this repository. Runtime behavior in code and tests remains the source of truth.

Machine-readable starter schemas are checked in under `docs/schemas/`, with matching fixtures under `tests/fixtures/contracts/`.

## Telemetry Ingestion

MQTT topic:

```text
senior-pomidor/{device_id}/telemetry
```

HTTP endpoint:

```text
POST /api/v1/edge/telemetry
Content-Type: application/json
Authorization: Bearer <TELEMETRY_UPLOAD_TOKEN>  # only when configured
```

Supported telemetry schemas:

- `senior-pomidor.edge.telemetry.v1`
- `senior-pomidor.edge.telemetry.v2`

Required fields:

- `schema_version`, or compatibility alias `schema`
- `device_id`
- `timestamp_utc`, or compatibility alias `timestamp`

Timestamps must be UTC ISO strings ending in `Z`. `device_id` and pod keys may contain only letters, digits, `_`, `.`, and `-`.

Pod readings may be sent as a list or object through `pods`, `pod_readings`, `plant.readings`, or `plant.pods`. Known numeric metrics are stored in typed columns. Unknown numeric metrics remain forward-compatible in `metrics_jsonb`.

Telemetry v2 may include optional `system_health`:

- `rpi_core`: `cpu_temp_c`, `wifi_rssi_dbm`, `disk_usage_percent`, `io_wait_percent`
- `pod_1_hardware`: `bus_voltage_v`, `bus_current_ma`, optional `box_climate.air_temp_c`, `box_climate.air_humidity_percent`
- `network`: booleans `wifi_connected`, `interface_up`, `default_gateway_reachable`, `dns_resolution_ok`, `internet_reachable`, `active_profile_present`, `preferred_profile_present`; strings `ssid`, `ip_address`, `last_recovery_action`, `last_recovery_result`, `last_recovery_at_utc`; integers `wifi_profile_count`, `last_recovery_exit_code`
- `errors`: list of objects with optional `sensor` and required `message`

Invalid schema names, malformed timestamps, unsafe identifiers, and wrong typed `system_health` fields return HTTP `400` for HTTP ingestion and are rejected by the MQTT worker.

## Photo Upload

HTTP endpoint:

```text
POST /api/v1/edge/photos
Content-Type: multipart/form-data
Authorization: Bearer <PHOTO_UPLOAD_TOKEN>  # only when configured
```

Required form fields:

- `photo_id`
- `device_id`
- `captured_at_utc`
- `schema_version=senior-pomidor.edge.photo.v1`
- `photo`: JPEG file field

Optional form fields:

- `sharpness_score`

Uploads are idempotent by `photo_id`. The server rejects invalid schema names, invalid timestamps, unsafe identifiers, non-JPEG content, oversized photos, and invalid bearer tokens.

## Read APIs

Implemented read endpoints:

- `GET /api/v1/devices`
- `GET /api/v1/devices/latest`
- `GET /api/v1/devices/{device_id}/latest`
- `GET /api/v1/devices/{device_id}/telemetry?from=&to=&since_hours=&pod=&limit=`
- `GET /api/v1/devices/{device_id}/photos?from=&to=&limit=`
- `GET /api/v1/photos/recent?from=&to=&limit=`
- `GET /api/v1/photos/{photo_id}`
- `GET /health`
- `GET /ready`
- `GET /dashboard`

Latest and history telemetry responses include pod readings, pod errors, preserved `system_health`, and derived `health_alerts`.

## Operational Boundaries

Current capabilities include telemetry v1/v2 ingestion, MQTT ingestion, HTTP fallback ingestion, photo upload/list/download, local dashboard, Grafana/PostgreSQL observability, Grafana Cloud public metrics export, public status JSON, and offline AI analysis.

Deferred or out of scope for the active contract:

- physical actuation, GPIO control, pump/fan/shade/fertilizer commands
- prototype-only `state_v1`, `action_v1`, `anomaly_v1`, `forecast_36h_v1`, `targets_v1`, and `sampling_plan_v1`
- weather-adapted targets or control-loop scheduling
- public dataset publishing APIs
