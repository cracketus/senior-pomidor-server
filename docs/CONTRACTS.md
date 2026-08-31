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
- `aggregate`: optional `senior-pomidor.edge.health.v1` object with bounded `schema_version`,
  `state` (`STARTUP|OK|BACKLOG|DEGRADED|MAINTENANCE|CRITICAL`), and unique bounded `reasons`

Telemetry v2 producers may additionally send edge reliability diagnostics. The producer contract in
`docs/schemas/telemetry-v2.schema.json` is strict for known fields: counters, byte sizes, process IDs,
and durations are non-negative integers; `disk_usage_percent` is `0..100`; estimates and CPU percent
are non-negative numbers; timestamps are valid UTC ISO strings ending in `Z`; and state, code, and
identifier strings are non-empty and at most 256 characters. Known reliability blocks are:

- `watchdog`: state/reason/result, suppression and configured flags, recovery counters, last healthy
  heartbeat timestamp, and boot ID
- `spool`: queue/delivery/reconciliation counters, database/free-space bytes, disk state and usage,
  backlog/outage ages, delivery and worker status/timestamps, and drain/retention estimates
- `application`: explicit `service_manager` (`none|systemd`), process liveness, PID, uptime, RSS and CPU,
  plus systemd availability, service identity, state/substate, active flag, and main PID. New process-only
  producers must send `service_manager=none`; a bare `process_running` value is incomplete.

The server reader is deliberately tolerant for these three additive blocks. A missing block remains
missing; an object is preserved even when all its fields are dropped, yielding `{}`. Known nullable
status, timestamp, age, and estimate fields preserve explicit `null`. An individual malformed or unknown
field is ignored without rejecting the telemetry record, and booleans are never accepted as integers.
This tolerant behavior does not weaken the producer schema and does not change existing strict validation
for `rpi_core`, `pod_1_hardware`, `network`, or `errors`.

`application.service_manager` is the one presence-sensitive exception: if the field is present but malformed
or outside `none|systemd`, normalization stores JSON `null` as a bounded internal invalid marker. The producer
schema still rejects `null`. Evaluators and dashboards distinguish that marker from an absent discriminator and
report `UNKNOWN`; only an actually absent discriminator may enter the temporary legacy-systemd fallback.

Roll out the application discriminator Core-first: deploy the tolerant server reader, then update Docker Edge
producers to send `service_manager=none` and systemd producers to send `service_manager=systemd`. During the
one-release compatibility window, complete legacy systemd payloads remain accepted; ambiguous bare process
telemetry remains `UNKNOWN` rather than being inferred healthy. Remove the legacy systemd fallback only in a
later coordinated contract revision after copied old-Edge fixtures and canary evidence show the window is closed.
The telemetry-v2 producer schema therefore continues to accept discriminator-absent partial `application`
objects during this window; schema acceptance preserves compatibility and does not promote incomplete evidence
to a healthy runtime state.

Only the documented allowlist is copied into `system_health_jsonb`. In particular, arbitrary
`last_error_detail`, `worker_last_error`, nested application errors, and unknown fields are not persisted.
The raw ingestion payload and `record_id` idempotency behavior are unchanged. The aggregate is normalized
and persisted as the canonical Edge health signal. Unknown fields and invalid individual aggregate fields
are dropped; a present malformed/unknown aggregate evaluates to `UNKNOWN` rather than being inferred healthy.
The server maps `OK` to `OK`, backlog/degraded/maintenance/startup to `WARN`, and critical to `ALERT`;
component `ALERT` or `UNKNOWN` findings always take precedence.

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
- `GET /api/v1/operator/edges/{device_id}/reliability`
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
The private API derives deterministic reliability alerts from the three reliability blocks. Only
`WARN` and `ALERT` findings are appended to `health_alerts`, with metrics `edge_watchdog`, `edge_spool`,
or `edge_application`, fixed `reason_code` values prefixed by that metric, fixed messages, and levels
`warning` or `critical`. Missing, incomplete, or unrecognized reliability input evaluates to `UNKNOWN`
and does not create a legacy-visible alert. Existing numeric, network, and probe-error alert objects
retain their prior shape. Edge-provided reason/error details, paths, service names, boot IDs, and
counters are never copied into derived alerts.

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

Only a node-scoped response adds `components.edge_reliability`. It contains the aggregate status,
telemetry age, ordered/deduplicated `reason_codes`, and bounded watchdog/spool/application projections.
The evaluator uses severity precedence `ALERT > WARN > UNKNOWN > OK`. Docker process-only application
telemetry is identified only by explicit `service_manager=none`: boolean `process_running=true` is `OK`,
false is `ALERT`, and missing/invalid process state or contradictory systemd fields are `UNKNOWN`. New systemd
producers send `service_manager=systemd`. During the one-release compatibility window, a legacy payload without
the discriminator is treated as systemd only when `process_running`, `systemd_available`, and
`systemd_service_active` are all present; otherwise it is `UNKNOWN`. Watchdog recovery and transitions
are warnings; suppression, exhausted budget, and failed recovery are alerts. Spool backlog and disk
warnings are warnings; degraded/critical spool or disk state and worker errors are alerts. A stopped
process or inactive systemd service is an alert; unavailable expected systemd or contradictory service
state is a warning. `configured=false` is a normal disabled watchdog. Missing, partial, unavailable, or
unrecognized state is never treated as healthy.

When node telemetry is missing, stale, timestamp-invalid, or unavailable, old reliability values are
not evaluated. The component is `UNKNOWN` with one of
`edge_reliability_telemetry_missing|stale|unavailable`. Summary reasons remain deterministic,
deduplicated, and globally limited to 20. A request without `node_id` omits `edge_reliability`, preserving
server-only `health_summary_v1` behavior. The evaluator is observational only: it does not copy edge
recovery policy or perform any action.

```json
{
  "edge_reliability": {
    "status": "WARN",
    "age_seconds": 12,
    "reason_codes": ["edge_watchdog_restart_recovery"],
    "watchdog": {
      "status": "WARN",
      "state": "recovering",
      "result": "restart_accepted",
      "suppression": false
    },
    "spool": {"status": "OK", "reported_status": "OK", "disk_status": "OK"},
    "application": {"status": "OK", "process_running": true, "systemd_service_active": true}
  }
}
```

Public status continues to publish only its existing sanitized projection. Its aggregate state may
become `degraded` because it counts private alerts, but it does not publish reliability reason codes or
payload fields. The optional Grafana Cloud projection adds only the bounded reliability metrics documented
below; it never exports the private response's reasons or unrestricted payload fields.

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

### Operator edge reliability v1

The private/LAN operator endpoint below returns the current watchdog, spool, and application state from
the deterministically selected latest telemetry row (`timestamp_utc DESC, id DESC`):

```text
GET /api/v1/operator/edges/{device_id}/reliability
```

Its response contract is `senior-pomidor.operator.edge-reliability.v1`, defined by
[`operator-edge-reliability-v1.schema.json`](schemas/operator-edge-reliability-v1.schema.json). A
sanitized synthetic example is maintained as
[`operator_edge_reliability_v1.json`](../tests/fixtures/contracts/operator_edge_reliability_v1.json).
All nullable fields remain present as JSON `null`; consumers do not need to distinguish an absent key.
The response is a bounded allowlist and excludes the raw payload, raw watchdog reason, boot ID, service
name, process IDs, paths, error details, and unrestricted health dictionaries.

Freshness uses the observation `timestamp_utc` and a 1200-second maximum age. Ages from zero through
exactly 1200 seconds are `FRESH`, and the shared edge reliability evaluator supplies all status and reason
mappings. Older observations are `STALE`: overall and subsystem statuses become `UNKNOWN`, the sole reason
is `edge_reliability_telemetry_stale`, and safe fields remain visible as last-observed values. A future or
invalid timestamp produces freshness/status `UNKNOWN`, reason `edge_reliability_telemetry_unavailable`, and
no reliability details. Missing or partial reliability blocks in fresh telemetry retain the evaluator's
`UNKNOWN` findings while other present blocks remain visible.

Unsafe device IDs return HTTP `400`, a device without telemetry returns `404`, and a database read failure
returns `503` with a fixed bounded detail. The endpoint introduces no new authentication mechanism and
inherits the existing trusted private/LAN read-API boundary. Existing latest/history responses,
`health_summary_v1`, and public status are unchanged. The Grafana Cloud exporter consumes the same latest
telemetry row independently and does not alter this HTTP response contract.

This per-edge current-state read model implements the reusable contract tracked by
[#204](https://github.com/cracketus/senior-pomidor-server/issues/204) and is the bounded input for the future
operator aggregation in [#205](https://github.com/cracketus/senior-pomidor-server/issues/205) and the
`pomidorctl` client/auth work in [#206](https://github.com/cracketus/senior-pomidor-server/issues/206).
Reliability history and metrics remain outside this contract.

### Edge reliability observability

The provisioned `Senior Pomidor Edge Reliability` dashboard (`uid=senior-pomidor-edge-reliability`) is a
trusted-LAN, read-only PostgreSQL consumer. Current-state queries start from `devices` and use a lateral
latest-event join ordered by `timestamp_utc DESC, id DESC`; a missing event, missing block, future timestamp,
stale observation, or unrecognized state is shown as `UNKNOWN`. History panels use only fixed state
allowlists and the normalized watchdog, spool, application, and canonical aggregate keys. The five
provisioned rules cover unavailable/stale evidence, critical watchdog recovery, critical
spool/disk/worker state, critical aggregate state, and inactive application process/service.
Notification routing remains outside this contract.

On every enabled exporter cycle, the latest telemetry event for each registered device is projected at the
export timestamp. This snapshot is repeated even when no new plant reading exists; the existing plant metric
timestamps, cursor, and checkpoint behavior are unchanged. Status metrics are one-hot state sets:

- `senior_pomidor_edge_reliability_status`, `senior_pomidor_edge_watchdog_status`,
  `senior_pomidor_edge_spool_status`, and `senior_pomidor_edge_application_status`:
  `OK|WARN|ALERT|UNKNOWN`;
- `senior_pomidor_edge_watchdog_state`: `healthy|starting|cooldown|maintenance|recovering|suppressed|`
  `budget_exhausted|recovery_suppressed|recovered|suppression_cleared|recovery_failed|unknown`;
- `senior_pomidor_edge_spool_disk_status`: `OK|WARNING|DEGRADED|CRITICAL|UNKNOWN`;
- `senior_pomidor_edge_reliability_freshness_status`: `FRESH|STALE|UNKNOWN`.

The exporter emits numeric gauges only when a normalized value exists:

- watchdog: `senior_pomidor_edge_watchdog_suppression`, `senior_pomidor_edge_watchdog_configured`,
  `senior_pomidor_edge_watchdog_attempt_count`, `senior_pomidor_edge_watchdog_restart_count`,
  `senior_pomidor_edge_watchdog_reboot_count`, and
  `senior_pomidor_edge_watchdog_healthy_heartbeat_age_seconds`;
- spool: `senior_pomidor_edge_spool_pending_records`, `senior_pomidor_edge_spool_backlog_records`,
  `senior_pomidor_edge_spool_in_flight_records`, `senior_pomidor_edge_spool_dead_letter_records`,
  `senior_pomidor_edge_spool_oldest_pending_age_seconds`,
  `senior_pomidor_edge_spool_outage_duration_seconds`, `senior_pomidor_edge_spool_database_size_bytes`,
  `senior_pomidor_edge_spool_free_space_bytes`, and `senior_pomidor_edge_spool_disk_usage_percent`;
- application: `senior_pomidor_edge_application_process_running`,
  `senior_pomidor_edge_application_process_uptime_seconds`,
  `senior_pomidor_edge_application_systemd_available`, and
  `senior_pomidor_edge_application_systemd_service_active`;
- overall: `senior_pomidor_edge_reliability_freshness_seconds`.

It does not invent zero for a missing value and does not publish backlog bytes. The only labels are sanitized
`device_id` and the fixed `status` or `state` label of a state set. Reason/result/error strings, boot IDs,
service names, PIDs, network identifiers, paths, raw JSON, and arbitrary labels are excluded. PostgreSQL
remains the source of truth.

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

## Release qualification artifacts

Release qualification uses three internal, machine-readable contracts. They do not change telemetry,
storage, read APIs, or public output:

- `senior-pomidor.system-invariants.v1` records the exact Core and Edge revisions/images plus deterministic
  current-system invariant scenarios. The server CI/tooling is the producer; the RC workflow and reviewer are
  consumers. Stable `sp-inv-001..008` definitions and positive/failure test mappings live in
  `docs/system-invariants-v1.yaml`. The three action/control scenarios remain `NOT_IMPLEMENTED` and `NOT_RUN`
  until the physical Control/Guardrails/Executor subsystem exists.
- `senior-pomidor.edge-core-compatibility-report.v1` is produced by the approved real Edge/Core staging
  workflow. It records the supported old-Edge/new-Core and new-Edge/rollback-Core window and all required
  outage, drain, retry, duplicate, restart, backlog, watchdog, spool, and time-order scenarios. Server-only or
  synthetic evidence cannot satisfy its RC gate.
- `senior-pomidor.release-validation.v1` is assembled by the release owner after software, Docker, staging,
  exact-bundle rehearsal, canary, rollback, and observation. The RC workflow and epic #225 evidence record are
  consumers. A release report cannot pass while any required gate or implemented scenario is `FAIL` or
  `NOT_RUN`.

All three contracts require 40-character lowercase Git SHAs, immutable `sha256` image digests, UTC timestamps
ending in `Z`, unique bounded scenario IDs, non-negative generated/persisted/read-back/duplicate/missing/unknown
counts, bounded alert outcomes, and an aggregate `PASS|FAIL|NOT_RUN`. `persisted` cannot exceed `generated`, and
`read_back` cannot exceed `persisted`. Reports are sanitized evidence: they must not contain raw payloads,
reasons/errors, boot IDs, paths, service names, network identifiers, credentials, or unbounded logs.

For compatibility reports, `generated` counts unique scientific observations; delivery retries are counted in
`duplicates`. Every required PASS scenario has at least one generated observation, zero missing observations,
and exact `generated == persisted == read_back` counts. Image references must end in and match the declared
immutable digest. Release PASS additionally enforces at least 24 hours for cross-repository staging and production
observation, at least 60 minutes for the canary, and a positive duration for every other gate.

Schemas are stored under `docs/schemas/`. `python -m tools.release_qualification validate` performs schema and
semantic checks; `--require-pass` also requires real staging/rehearsal evidence for compatibility and the exact
CI/staging/rehearsal/canary/production scope for each release gate.

## Operational Boundaries

Current capabilities include telemetry v1/v2 ingestion, MQTT ingestion, HTTP fallback ingestion, photo upload/list/download, local dashboard, Grafana/PostgreSQL observability, Grafana Cloud public metrics export, public status JSON, and offline AI analysis.
Current capabilities also include `state_v1`, `sensor_health_v1`, `anomaly_v1`, and private estimator JSONL logs.

Deferred or out of scope for the active contract:

- physical actuation, GPIO control, pump/fan/shade/fertilizer commands
- prototype-only `action_v1`, `forecast_36h_v1`, `targets_v1`, and `sampling_plan_v1`
- weather-adapted targets or control-loop scheduling
- public dataset publishing APIs

Current public outputs are limited to sanitized status JSON from `tools.public_status` and optional low-cardinality Grafana Cloud metrics export. Raw telemetry, raw photo metadata, stored photos, and database exports are not public dataset APIs.
