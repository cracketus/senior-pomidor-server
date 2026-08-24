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

- `senior-pomidor.edge.telemetry.v1`: frozen for this release.
- `senior-pomidor.edge.telemetry.v2`: active in this release and may evolve in later releases.

Required fields:

- `schema_version`, or compatibility alias `schema`
- `device_id`
- `timestamp_utc`, or compatibility alias `timestamp`

Telemetry v2 producers should also send `record_id`, a globally unique durable-spool identifier of 1-128
characters from `A-Za-z0-9_.:-`. It remains optional for one release cycle so already-deployed legacy
producers continue to ingest. Empty, oversized, or unsafe `record_id` values are rejected with HTTP `400`.

Timestamps must be UTC ISO strings ending in `Z`. `device_id` and pod keys may contain only letters, digits, `_`, `.`, and `-`.

Pod readings may be sent as a list or object through `pods`, `pod_readings`, `plant.readings`, or `plant.pods`. Known numeric metrics are stored in typed columns. Unknown numeric metrics remain forward-compatible in `metrics_jsonb`.

Telemetry v2 may include optional `system_health`:

- `rpi_core`: `cpu_temp_c`, `wifi_rssi_dbm`, `disk_usage_percent`, `io_wait_percent`
- `pod_1_hardware`: `bus_voltage_v`, `bus_current_ma`, optional `box_climate.air_temp_c`, `box_climate.air_humidity_percent`
- `network`: booleans `wifi_connected`, `interface_up`, `default_gateway_reachable`, `dns_resolution_ok`, `internet_reachable`, `active_profile_present`, `preferred_profile_present`; strings `ssid`, `ip_address`, `last_recovery_action`, `last_recovery_result`, `last_recovery_at_utc`; integers `wifi_profile_count`, `last_recovery_exit_code`
- `errors`: list of objects with optional `sensor` and required `message`

Telemetry v2 producers may additionally send edge reliability diagnostics. The producer contract in
`docs/schemas/telemetry-v2.schema.json` is strict for known fields: counters, byte sizes, process IDs,
and durations are non-negative integers; `disk_usage_percent` is `0..100`; estimates and CPU percent
are non-negative numbers; timestamps are valid UTC ISO strings ending in `Z`; and state, code, and
identifier strings are non-empty and at most 256 characters. Known reliability blocks are:

- `watchdog`: state/reason/result, suppression and configured flags, recovery counters, last healthy
  heartbeat timestamp, and boot ID
- `spool`: queue/delivery/reconciliation counters, database/free-space bytes, disk state and usage,
  backlog/outage ages, delivery and worker status/timestamps, and drain/retention estimates
- `application`: process liveness, PID, uptime, RSS and CPU, plus systemd availability, service identity,
  state/substate, active flag, and main PID

The server reader is deliberately tolerant for these three additive blocks. A missing block remains
missing; an object is preserved even when all its fields are dropped, yielding `{}`. Known nullable
status, timestamp, age, and estimate fields preserve explicit `null`. An individual malformed or unknown
field is ignored without rejecting the telemetry record, and booleans are never accepted as integers.
This tolerant behavior does not weaken the producer schema and does not change existing strict validation
for `rpi_core`, `pod_1_hardware`, `network`, or `errors`.

Only the documented allowlist is copied into `system_health_jsonb`. In particular, arbitrary
`last_error_detail`, `worker_last_error`, nested application errors, and unknown fields are not persisted.
The raw ingestion payload and `record_id` idempotency behavior are unchanged. `aggregate` and `indicator`
remain outside this server normalization contract.

Malformed JSON and invalid `record_id` values return HTTP `400` because the server cannot trust a correlation
identifier. Invalid schema names, malformed timestamps, unsafe identifiers, and wrong typed `system_health`
fields without a valid `record_id` also return HTTP `400` and are rejected by the MQTT worker.

Example HTTP request:

```powershell
$body = @{
  schema_version = 'senior-pomidor.edge.telemetry.v2'
  record_id = 'spool:pi-001:20260702T120000Z'
  device_id = 'pi-001'
  timestamp_utc = '2026-07-02T12:00:00Z'
  pods = @{
    pod_1 = @{
      enabled = $true
      metrics = @{
        soil_moisture_percent = 42.5
        air_vpd_kpa = 1.1
        light_lux = 18000
      }
    }
  }
  system_health = @{
    rpi_core = @{ cpu_temp_c = 45.0; wifi_rssi_dbm = -55.0 }
    network = @{
      wifi_connected = $true
      wifi_profile_count = 2
      internet_reachable = $true
      dns_resolution_ok = $true
      last_recovery_result = 'not_needed'
      last_recovery_exit_code = 0
    }
    errors = @()
  }
} | ConvertTo-Json -Depth 8

Invoke-RestMethod `
  -Method Post `
  -Uri http://localhost:8000/api/v1/edge/telemetry `
  -ContentType 'application/json' `
  -Body $body
```

First committed delivery with `record_id` returns HTTP `202`:

```json
{"record_id":"spool:pi-001:20260702T120000Z","status":"accepted"}
```

An identical replay, including after a lost acknowledgement or through the other transport, returns HTTP
`202` with exactly `{"record_id":"...","status":"duplicate"}`. Both outcomes allow the released edge
spool to mark the record delivered. MQTT and HTTP use the same stored identity and never create a second row.

A valid `record_id` paired with a permanently invalid payload returns HTTP `200` and
`{"record_id":"...","status":"rejected","error_code":"invalid_payload"}`. Reusing a `record_id` for
different content returns `record_id_conflict`; using a different `record_id` for the existing
`(device_id, timestamp_utc, schema_version)` observation returns `observation_identity_conflict`. The original
row is never overwritten. A transient database failure returns HTTP `503` with
`{"record_id":"...","status":"retry","error_code":"storage_unavailable"}` and no database details.

For the one-release-cycle compatibility window, payloads without `record_id` keep the legacy identity
deduplication and HTTP `202` response `{"accepted":true,"event_id":1}`.

Invalid payload example:

```json
{
  "schema_version": "senior-pomidor.edge.telemetry.v2",
  "device_id": "pi-001",
  "timestamp_utc": "2026-07-02T12:00:00+00:00"
}
```

HTTP response:

```json
{
  "detail": "timestamp must be a UTC ISO string ending in Z"
}
```

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
New uploads return HTTP `202`; repeated uploads with the same `photo_id` return HTTP `200` with the existing metadata.

Example upload:

```powershell
curl.exe -X POST http://localhost:8000/api/v1/edge/photos `
  -F "photo_id=pi-001-20260702T120000Z" `
  -F "device_id=pi-001" `
  -F "captured_at_utc=2026-07-02T12:00:00Z" `
  -F "schema_version=senior-pomidor.edge.photo.v1" `
  -F "sharpness_score=0.91" `
  -F "photo=@sample.jpg;type=image/jpeg"
```

Successful first-upload response:

```json
{
  "accepted": true,
  "created": true,
  "photo": {
    "photo_id": "pi-001-20260702T120000Z",
    "device_id": "pi-001",
    "captured_at_utc": "2026-07-02T12:00:00Z",
    "schema_version": "senior-pomidor.edge.photo.v1",
    "sharpness_score": 0.91,
    "content_type": "image/jpeg",
    "file_size_bytes": 123456,
    "sha256": "<sha256>",
    "received_at": "2026-07-02T12:00:01Z"
  }
}
```

Known consistency limitation: photo metadata is committed before the final `os.replace` moves the JPEG into place. A crash between those steps could leave a photo row whose file is missing; `GET /api/v1/photos/{photo_id}` then returns `404`, and `python tools/check_photo_storage.py` can be used to find mismatches.

## Read APIs

Implemented read endpoints:

- `GET /api/v1/devices`
- `GET /api/v1/devices/latest`
- `GET /api/v1/devices/{device_id}/latest`
- `GET /api/v1/devices/{device_id}/telemetry?from=&to=&since_hours=&pod=&limit=`
- `GET /api/v1/state/latest?node_id=`
- `GET /api/v1/state/range?node_id=&from=&to=&limit=`
- `GET /api/v1/sensor-health/latest?node_id=`
- `GET /api/v1/anomalies/active?node_id=`
- `GET /api/v1/devices/{device_id}/photos?from=&to=&limit=`
- `GET /api/v1/photos/recent?from=&to=&limit=`
- `GET /api/v1/photos/{photo_id}`
- `GET /health`
- `GET /health/summary?node_id=` (read-only `health_summary_v1`)
- `GET /ready`
- `GET /dashboard`

Latest and history telemetry responses include pod readings, pod errors, preserved `system_health`, and derived `health_alerts`.
They also include nullable `record_id`; historical and compatibility-window events without it return `null`.
The reliability blocks above appear only inside the existing private `system_health` response. This
contract does not assign them health-alert or health-summary semantics and does not add them to public
status or the Grafana Cloud projection.

The health summary is an internal, read-only composition of existing server, worker, telemetry,
and sensor-health signals. It does not restart services, mutate storage, invoke recovery, or publish
an export. `node_id` is optional: without it, telemetry and sensor-health components are marked as
server-scope and do not assert node health. With it, missing or stale node data is non-healthy.

Example:

```powershell
Invoke-RestMethod "http://localhost:8000/health/summary?node_id=pi-001"
```

The response uses `schema_version: "health_summary_v1"`, UTC `generated_at`, status values
`OK|WARN|ALERT|UNKNOWN`, bounded reason codes, and `data_freshness`. Worker health is stale after
90 seconds; telemetry and sensor health are stale after 1200 seconds. `OK` is returned only when
all required scoped evidence is current and healthy.

Example latest telemetry call:

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/devices/pi-001/latest
```

Example response:

```json
{
  "id": 1,
  "record_id": "spool:pi-001:20260702T120000Z",
  "device_id": "pi-001",
  "timestamp_utc": "2026-07-02T12:00:00Z",
  "schema_version": "senior-pomidor.edge.telemetry.v2",
  "source": "http",
  "received_at": "2026-07-02T12:00:01Z",
  "plant": {
    "readings": [
      {
        "pod_key": "pod_1",
        "enabled": true,
        "metrics": {
          "soil_moisture_percent": 42.5,
          "air_vpd_kpa": 1.1,
          "light_lux": 18000
        }
      }
    ],
    "errors": []
  },
  "system_health": {
    "rpi_core": {
      "cpu_temp_c": 45.0,
      "wifi_rssi_dbm": -55.0
    }
  },
  "health_alerts": [],
  "readings": [
    {
      "pod_key": "pod_1",
      "enabled": true,
      "metrics": {
        "soil_moisture_percent": 42.5,
        "air_vpd_kpa": 1.1,
        "light_lux": 18000
      }
    }
  ],
  "errors": []
}
```

Example history query:

```powershell
Invoke-RestMethod "http://localhost:8000/api/v1/devices/pi-001/telemetry?since_hours=24&pod=pod_1&limit=100"
```

History responses are arrays of the same event shape used by the latest telemetry endpoint.

## State Estimator v1

The server implements `state_v1`, `sensor_health_v1`, `anomaly_v1`, and estimator diagnostics from current telemetry v1/v2 rows. Edge nodes do not need to send `raw_observation_v1` yet; existing pod metrics are adapted internally:

- `air_temperature_c` and `air_humidity_percent` become `state_v1.env.air_temp_c` and `state_v1.env.rh_pct`
- `soil_moisture_percent` becomes `state_v1.soil.probes[].moisture_pct`
- `soil_temperature_c` becomes `state_v1.soil.temp_c`
- `light_lux` becomes `state_v1.env.lux`
- `leaf_temp_c` becomes `state_v1.plant.leaf_temp_c`

Incoming legacy `air_vpd_kpa` and `leaf_vpd_kpa` remain telemetry diagnostics only; canonical VPD values are recomputed by the estimator.

State snapshots are persisted in `state_snapshots`, sensor health in `sensor_health_snapshots`, active/cleared anomaly records in `anomaly_records`, and diagnostics in `estimator_diagnostics`. Private JSONL logs are appended under `STATE_ESTIMATOR_PRIVATE_LOG_DIR` when snapshots are generated.

The local replay endpoint is disabled by default:

```text
POST /api/v1/state-estimator/replay
```

Set `STATE_ESTIMATOR_REPLAY_ENABLED=true` to enable it for local deterministic replay inputs.

## Operational Boundaries

Current capabilities include telemetry v1/v2 ingestion, MQTT ingestion, HTTP fallback ingestion, photo upload/list/download, local dashboard, Grafana/PostgreSQL observability, Grafana Cloud public metrics export, public status JSON, and offline AI analysis.
Current capabilities also include `state_v1`, `sensor_health_v1`, `anomaly_v1`, and private estimator JSONL logs.

Deferred or out of scope for the active contract:

- physical actuation, GPIO control, pump/fan/shade/fertilizer commands
- prototype-only `action_v1`, `forecast_36h_v1`, `targets_v1`, and `sampling_plan_v1`
- weather-adapted targets or control-loop scheduling
- public dataset publishing APIs

Current public outputs are limited to sanitized status JSON from `tools.public_status` and optional low-cardinality Grafana Cloud metrics export. Raw telemetry, raw photo metadata, stored photos, and database exports are not public dataset APIs.
