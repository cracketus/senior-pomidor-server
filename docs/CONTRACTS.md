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

Timestamps must be UTC ISO strings ending in `Z`. `device_id` and pod keys may contain only letters, digits, `_`, `.`, and `-`.

Pod readings may be sent as a list or object through `pods`, `pod_readings`, `plant.readings`, or `plant.pods`. Known numeric metrics are stored in typed columns. Unknown numeric metrics remain forward-compatible in `metrics_jsonb`.

Telemetry v2 may include optional `system_health`:

- `rpi_core`: `cpu_temp_c`, `wifi_rssi_dbm`, `disk_usage_percent`, `io_wait_percent`
- `pod_1_hardware`: `bus_voltage_v`, `bus_current_ma`, optional `box_climate.air_temp_c`, `box_climate.air_humidity_percent`
- `network`: booleans `wifi_connected`, `interface_up`, `default_gateway_reachable`, `dns_resolution_ok`, `internet_reachable`, `active_profile_present`, `preferred_profile_present`; strings `ssid`, `ip_address`, `last_recovery_action`, `last_recovery_result`, `last_recovery_at_utc`; integers `wifi_profile_count`, `last_recovery_exit_code`
- `errors`: list of objects with optional `sensor` and required `message`

Invalid schema names, malformed timestamps, unsafe identifiers, and wrong typed `system_health` fields return HTTP `400` for HTTP ingestion and are rejected by the MQTT worker.

Example HTTP request:

```powershell
$body = @{
  schema_version = 'senior-pomidor.edge.telemetry.v2'
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

Successful HTTP response:

```json
{
  "accepted": true,
  "event_id": 1
}
```

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
- `GET /ready`
- `GET /dashboard`

Latest and history telemetry responses include pod readings, pod errors, preserved `system_health`, and derived `health_alerts`.

Example latest telemetry call:

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/devices/pi-001/latest
```

Example response:

```json
{
  "id": 1,
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
