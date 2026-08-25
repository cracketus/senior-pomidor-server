# Senior Pomidor Server Operations

## Architecture

```text
Raspberry Pi edge nodes
  |-- MQTT telemetry --> mosquitto --> worker ----.
  `-- HTTP telemetry/photos --> FastAPI API ------+--> PostgreSQL <-- state-estimator-worker
                                                   |                  `--> private JSONL volume
                                                   `--> photo volume

FastAPI API --> /dashboard and /api/v1 read APIs
PostgreSQL --> Grafana local dashboard and alerts using raw telemetry and canonical state
PostgreSQL --> optional Grafana Cloud exporter with sanitized low-cardinality plant/reliability metrics
```

The API, MQTT broker, PostgreSQL port, dashboard, and Grafana UI are intended for trusted LAN use. For any remote access, put the service behind a VPN, firewall allow-list, or reverse proxy with authentication and TLS.

## Release Checklist

Before tagging or publishing a server release:

- Run `python -m pytest -q`.
- Run `nox -s lint format_check types security`.
- Run `nox -s deps_audit`.
- Run `$env:RUN_DOCKER_E2E='1'; python -m pytest -q tests/test_docker_e2e.py` when Docker is available.
- Verify `GET /health` and `GET /ready` after a local development-overlay build or tagged production deployment.
- For a read-only machine summary, inspect `GET /health/summary` or add `?node_id=pi-001`; treat
  `WARN`, `ALERT`, and `UNKNOWN` as degraded evidence, not as a request to restart or recover a service.
- Confirm there are no local `.env`, private key, known-hosts, `.db`, `data/`, or `backups/` files in the release checkout.
- Confirm `.env.example` still uses local bootstrap defaults only, and document any required production overrides.
- Verify `python -m tools.edge_readiness --api-base-url http://127.0.0.1:8000 --mqtt-host 127.0.0.1 --photo-storage-dir data/photos`.
- Verify `python -m tools.backup` can write and verify a complete snapshot outside the repository.
- Confirm release notes state the trusted-LAN security boundary, optional bearer-token behavior, MQTT default auth posture, and public dataset/export limitations.
- Confirm `git status -sb` is clean on the intended release branch before tagging.

## LAN Deployment Checklist

1. Install Docker Engine or Docker Desktop on the home server.
2. Confirm Docker is running:

   ```powershell
   docker compose version
   docker info
   ```

3. Create a `.env` file when defaults need to change:

   ```powershell
   Copy-Item .env.example .env
   ```

4. Confirm required LAN ports are available:
   - API: `8000/tcp`
   - MQTT broker: `1883/tcp`
   - PostgreSQL: `5432/tcp`, only needed for local administration
   - Grafana: `3000/tcp`, only needed when the observability profile is enabled

   Override the published host ports with `API_PUBLISHED_PORT`, `MQTT_PUBLISHED_PORT`, `POSTGRES_PUBLISHED_PORT`, and `GRAFANA_PUBLISHED_PORT` in `.env` if any defaults are already in use.
   Treat all published ports as LAN-only. Use a VPN, firewall allow-list, or reverse proxy with authentication/TLS before any remote access.

5. Start the stack. The one-shot `migrate` service applies Alembic migrations before the API, MQTT worker, and state estimator worker start:

   ```powershell
   docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
   ```

6. Verify service health:

   ```powershell
   Invoke-RestMethod http://localhost:8000/health
   Invoke-RestMethod http://localhost:8000/ready
   python -m tools.edge_readiness --api-base-url http://127.0.0.1:8000 --mqtt-host 127.0.0.1 --photo-storage-dir data/photos
   docker compose ps
   docker compose logs --tail 100 api
   docker compose logs --tail 100 worker
   docker compose logs --tail 100 state-estimator-worker
   docker compose ps migrate
   ```

   `tools.edge_readiness` checks API health, database migration readiness, MQTT broker TCP reachability, and photo storage writability. Use `--json` for machine-readable output.

   Recreate containers after Compose healthcheck or dependency changes so Docker health metadata is active:

   ```powershell
   docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build --force-recreate
   ```

   Normal state estimator operation is worker-driven. The `GET /api/v1/state/latest` endpoint can still lazily create a snapshot for compatibility, but the Compose service should continuously refresh canonical state during normal operation.

   Verify state estimator health and outputs:

   ```powershell
   docker compose ps state-estimator-worker
   docker compose exec -T postgres psql -U senior_pomidor senior_pomidor -c "SELECT node_id, ts, payload_jsonb #>> '{quality,level}' AS quality_level, payload_jsonb #>> '{env,vpd_kpa}' AS vpd_kpa FROM state_snapshots ORDER BY ts DESC LIMIT 5;"
   docker compose exec -T postgres psql -U senior_pomidor senior_pomidor -c "SELECT node_id, ts, payload_jsonb ->> 'overall_status' AS overall_status FROM sensor_health_snapshots ORDER BY ts DESC LIMIT 5;"
   docker compose exec -T postgres psql -U senior_pomidor senior_pomidor -c "SELECT node_id, type, severity, status, ts FROM anomaly_records ORDER BY ts DESC LIMIT 10;"
   docker compose exec -T state-estimator-worker sh -c "find /app/data/private -maxdepth 1 -type f -name '*.jsonl' -print"
   ```

   Read-only 24h estimator audit:

   ```bash
   docker compose exec -T api python -m tools.state_estimator_audit --hours 24
   ```

7. Open the read-only dashboard:

   ```text
   http://localhost:8000/dashboard
   ```

8. Optionally start Grafana for local observability:

   ```powershell
   docker compose --profile observability up -d grafana
   ```

   Grafana is available at `http://localhost:3000`. Default local admin credentials are defined by `GRAFANA_ADMIN_USER` and `GRAFANA_ADMIN_PASSWORD` in `.env.example`.
   Its PostgreSQL datasource uses `GRAFANA_DB_USER` and `GRAFANA_DB_PASSWORD`, which default to the readonly `grafana_reader` role.
   The `Senior Pomidor Alerts` rule group is provisioned in Grafana Alerting. This first version is Grafana-only and does not configure external email or webhook notifications.
   Confirm the telemetry dashboard includes the raw telemetry panels plus `Latest State Summary`, `Canonical Env VPD`, `State Confidence`, `Average Soil Moisture`, `Latest Sensor Health Summary`, and `Active Anomalies`.
   Confirm the separate `Senior Pomidor Edge Reliability` dashboard (`uid=senior-pomidor-edge-reliability`)
   includes current states, suppression/recovery counters, freshness, backlog/storage pressure, restart/reboot
   and backlog timelines, and a recovery/degradation state timeline. Missing or unrecognized evidence must
   display `UNKNOWN`.

   Sanitized synthetic example (`demo-edge-01`; no real timestamps, network identifiers, or raw reasons):

   ![Sanitized synthetic Edge Reliability dashboard](images/edge-reliability-dashboard-demo.svg)

9. If the PostgreSQL volume already existed before Grafana DB access was configured, re-apply the readonly role and grants after migrations:

   ```powershell
   docker compose exec -T postgres sh /docker-entrypoint-initdb.d/20-grafana-reader.sh
   ```

   Verify the Grafana user can read telemetry tables:

   ```powershell
   docker compose exec -T postgres psql "postgresql://grafana_reader:grafana_reader@localhost:5432/senior_pomidor" -c "SELECT count(*) FROM devices;"
   docker compose exec -T postgres psql "postgresql://grafana_reader:grafana_reader@localhost:5432/senior_pomidor" -c "SELECT count(*) FROM telemetry_events;"
   docker compose exec -T postgres psql "postgresql://grafana_reader:grafana_reader@localhost:5432/senior_pomidor" -c "SELECT count(*) FROM pod_readings;"
   docker compose exec -T postgres psql "postgresql://grafana_reader:grafana_reader@localhost:5432/senior_pomidor" -c "SELECT count(*) FROM pod_errors;"
   docker compose exec -T postgres psql "postgresql://grafana_reader:grafana_reader@localhost:5432/senior_pomidor" -c "SELECT count(*) FROM photos;"
   docker compose exec -T postgres psql "postgresql://grafana_reader:grafana_reader@localhost:5432/senior_pomidor" -c "SELECT count(*) FROM state_snapshots;"
   docker compose exec -T postgres psql "postgresql://grafana_reader:grafana_reader@localhost:5432/senior_pomidor" -c "SELECT count(*) FROM sensor_health_snapshots;"
   docker compose exec -T postgres psql "postgresql://grafana_reader:grafana_reader@localhost:5432/senior_pomidor" -c "SELECT count(*) FROM anomaly_records;"
   docker compose exec -T postgres psql "postgresql://grafana_reader:grafana_reader@localhost:5432/senior_pomidor" -c "SELECT count(*) FROM estimator_diagnostics;"
   ```

   Verify the Grafana user cannot mutate tables:

   ```powershell
   docker compose exec -T postgres psql "postgresql://grafana_reader:grafana_reader@localhost:5432/senior_pomidor" -c "INSERT INTO devices (device_id, first_seen_at, last_seen_at, last_payload_at) VALUES ('readonly-check', now(), now(), now());"
   docker compose exec -T postgres psql "postgresql://grafana_reader:grafana_reader@localhost:5432/senior_pomidor" -c "UPDATE devices SET last_payload_at = now() WHERE device_id = 'readonly-check';"
   docker compose exec -T postgres psql "postgresql://grafana_reader:grafana_reader@localhost:5432/senior_pomidor" -c "DELETE FROM devices WHERE device_id = 'readonly-check';"
   ```

   Each mutation command should fail with a permission error.

## Raspberry Pi Edge Configuration

Use the home server LAN IP. For example, if the server is `192.168.1.50`:

```text
MQTT_HOST=192.168.1.50
MQTT_PORT=1883
MQTT_TOPIC_PREFIX=senior-pomidor
HTTP_ENABLED=true
CORE_HTTP_URL=http://192.168.1.50:8000/api/v1/edge/telemetry
PHOTO_UPLOAD_ENABLED=true
PHOTO_UPLOAD_URL=http://192.168.1.50:8000/api/v1/edge/photos
PHOTO_UPLOAD_TOKEN=<same value as server PHOTO_UPLOAD_TOKEN, if configured>
TELEMETRY_UPLOAD_TOKEN=<same value as server TELEMETRY_UPLOAD_TOKEN, if configured>
```

MQTT should be treated as the primary path. HTTP telemetry is the compatibility fallback and is open by default for trusted-LAN compatibility unless `TELEMETRY_UPLOAD_TOKEN` is configured.

## Backup And Restore

### Telemetry `record_id` rollout

Migration `0009_telemetry_record_id` adds a nullable unique column and leaves historical rows and the legacy
observation identity constraint unchanged. Roll out in this order: verify a fresh backup; rehearse upgrade and
restore in an isolated task; apply the additive migration; release the API and worker; send one canary record and
its identical replay; then replay the backlog in bounded groups.

Abort on a migration revision mismatch, changed historical row counts/raw-payload hashes/timestamps, a changed
legacy constraint, duplicate rows, an ACK that does not echo the canary `record_id`, or elevated retry/5xx results.
Rollback is application-only: restore the previous application image while retaining the nullable column/index.
Do not downgrade the migration or delete telemetry. Edge acquisition continues into its durable spool until a
forward application fix is available.

For longer-term sizing, retention, power estimates, and pod-count expansion
planning, see [CAPACITY_PLANNING.md](CAPACITY_PLANNING.md).
For public export boundaries, see [PUBLIC_DATA_POLICY.md](PUBLIC_DATA_POLICY.md).

From a Windows or Linux source checkout, create a complete timestamped snapshot outside the repository.
For a fresh checkout, first create the local development environment file from the checked-in
synthetic template; Compose requires its `APP_IMAGE` value even though the development overlay builds
the image locally. Do not commit the resulting `.env` file. In PowerShell:

```powershell
Copy-Item .env.example .env
docker compose --env-file .env -f docker-compose.yml -f docker-compose.dev.yml config --quiet
docker compose --env-file .env -f docker-compose.yml -f docker-compose.dev.yml up -d --build postgres mosquitto api worker state-estimator-worker
```

On Linux, use `cp .env.example .env` in place of `Copy-Item`. The command below then keeps PostgreSQL running
for a custom-format logical dump, briefly stops only active ingestion/file-writing services, archives
the application data mounts, and restores every service it stopped even when a component fails or the
process is interrupted:

```powershell
python -m tools.backup --backup-root D:\senior-pomidor-backups
```

Every backup subprocess has a 15-minute deadline. Restart commands use a 30-second command deadline,
and each stopped service must become running (and `healthy` when it defines a healthcheck) within 60
seconds. A timeout or failed post-restart health check keeps the snapshot incomplete and returns a
bounded failure; inspect and recover the named service before retrying.

The source-free Linux production bundle does not contain `tools.backup`. Use the bundled and installed
`backup.sh` entry point through its systemd units; it reads the deployment's exact environment and
Compose files. Daily runs create logical database backups, while weekly runs also stop active writers
and archive application data:

```bash
sudo systemctl start senior-pomidor-backup@daily.service
sudo systemctl start senior-pomidor-backup@weekly.service
sudo journalctl -u senior-pomidor-backup@daily.service -u senior-pomidor-backup@weekly.service
```

In the source-checkout Python workflow, include an environment file only by encrypting it directly
with `age`. Supplying an environment file without a recipient is rejected; no plaintext copy is
written to the snapshot:

```bash
python -m tools.backup \
  --backup-root /srv/backups/senior-pomidor/manual \
  --env-file /path/to/deployment.env \
  --age-recipient age1example-recipient
```

Use `--json` for the versioned machine-readable component result. The manifest records a hashed host
identity, Git commit, Compose project and image references, Alembic revision, service-recovery results,
sizes, archive names, and SHA-256 checksums. Verification rejects missing or contradictory provenance,
recovery, component, or artifact metadata. Verify the snapshot after creation or transfer:

```powershell
python -m tools.backup --verify D:\senior-pomidor-backups\snapshot-YYYYmmddTHHMMSSZ-xxxxxxxx --json
```

New snapshots use `senior-pomidor.backup-manifest.v2` and include `baseline-counts.csv` plus bounded
representative SHA-256 inventories for photo, estimator-private, and Mosquitto data. The verifier
continues to accept existing v1 snapshots under the v1 component rules; only v2 requires the restore
baselines.

`grafana_data` is archived only when a Grafana container exists for the selected Compose project; the
manifest records `absent` otherwise. Production Grafana remains platform-owned and must not be
lifecycle-managed by this application command.

The existing `tools/backup_data.ps1` remains available for the one-release compatibility window. On
source-free Linux production, keep the bundled `backup.sh` timers: they retain daily sets for 30 days
and weekly sets for 56 days. Do not migrate a scheduled job to `python -m tools.backup` until that
entry point is packaged for the target and an equivalent reviewed retention job plus isolated restore
rehearsal are in place.

Recommended schedule:

- Daily logical database snapshot and weekly complete application-data snapshot while the season is active.
- A separately scheduled isolated restore rehearsal; checksum verification alone is not recovery proof.
- Fresh backup before Docker image, schema, or host OS upgrades.
- Investigate disk usage at 70%; uploaded photos are the primary growth risk.

Emergency manual PostgreSQL backup (database only, not a complete server snapshot):

```powershell
docker compose exec -T postgres pg_dump -U $env:POSTGRES_USER $env:POSTGRES_DB > backups\senior_pomidor.sql
```

Emergency manual uploaded photo backup (not a complete server snapshot):

```powershell
tar.exe -czf backups/photo_data.tgz -C $env:PHOTO_DATA_DIR .
```

Restore PostgreSQL into an empty database:

```powershell
Get-Content backups\senior_pomidor.sql | docker compose exec -T postgres `
  psql -U $env:POSTGRES_USER -d $env:POSTGRES_DB
```

Restore uploaded photos:

```powershell
tar.exe -xzf backups/photo_data.tgz -C $env:PHOTO_DATA_DIR
```

Verify photo metadata and files agree:

```powershell
python tools/check_photo_storage.py
```

Restore drill (required before treating a snapshot as recovery evidence). `database.dump` is a
custom-format archive and must be restored with `pg_restore`, not `psql`. For a disposable local
development project on PowerShell, first point every data path at a new empty drill directory, start
only its PostgreSQL container, copy in the verified dump, and restore it:

```powershell
$snapshot = "D:\senior-pomidor-backups\snapshot-YYYYmmddTHHMMSSZ-xxxxxxxx"
$drillRoot = Join-Path $env:TEMP ("senior-pomidor-restore-drill-" + [guid]::NewGuid().ToString("N"))
$drillEnv = Join-Path $drillRoot "restore-drill.env"
$postgresDir = Join-Path $drillRoot "postgres"
$photoDir = Join-Path $drillRoot "photos"
$estimatorDir = Join-Path $drillRoot "estimator-private"
$mosquittoDir = Join-Path $drillRoot "mosquitto"
$grafanaDir = Join-Path $drillRoot "grafana"
$ollamaDir = Join-Path $drillRoot "ollama"
New-Item -ItemType Directory $drillRoot, $postgresDir, $photoDir, $estimatorDir, `
  $mosquittoDir, $grafanaDir, $ollamaDir | Out-Null

# Shell variables override --env-file, so remove every Compose-sensitive deployment override first.
$composeIsolationVars = @(
  "APP_IMAGE", "DATABASE_URL", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD",
  "POSTGRES_DATA_DIR", "PHOTO_DATA_DIR", "ESTIMATOR_PRIVATE_DATA_DIR", "MOSQUITTO_DATA_DIR",
  "GRAFANA_DATA_DIR", "OLLAMA_DATA_DIR", "LAN_BIND_ADDRESS", "POSTGRES_BIND_ADDRESS",
  "API_PUBLISHED_PORT", "MQTT_PUBLISHED_PORT", "POSTGRES_PUBLISHED_PORT", "GRAFANA_PUBLISHED_PORT",
  "OLLAMA_PUBLISHED_PORT", "COMPOSE_PROFILES", "COMPOSE_FILE", "COMPOSE_ENV_FILES",
  "COMPOSE_PROJECT_NAME", "GRAFANA_CLOUD_EXPORT_ENABLED", "GRAFANA_CLOUD_REMOTE_WRITE_URL",
  "GRAFANA_CLOUD_INSTANCE_ID", "GRAFANA_CLOUD_API_TOKEN", "GRAFANA_DB_USER",
  "GRAFANA_DB_PASSWORD", "MQTT_HOST", "MQTT_PORT", "MQTT_USERNAME", "MQTT_PASSWORD",
  "PHOTO_UPLOAD_TOKEN", "TELEMETRY_UPLOAD_TOKEN", "DOCKER_HOST", "DOCKER_CONTEXT",
  "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"
)
$composeIsolationVars | ForEach-Object { Remove-Item "Env:$_" -ErrorAction SilentlyContinue }
$dockerEndpoint = docker context inspect --format "{{.Endpoints.docker.Host}}"
if ($dockerEndpoint -notmatch "^(npipe://|unix://)") {
  throw "Restore drill requires a local Docker engine; refusing endpoint $dockerEndpoint"
}

$drillSettings = @(
  "APP_IMAGE=senior-pomidor-server:restore-drill",
  "POSTGRES_DB=senior_pomidor_drill",
  "POSTGRES_USER=restore_drill",
  "POSTGRES_PASSWORD=synthetic-restore-drill-only",
  "DATABASE_URL=postgresql+psycopg://restore_drill:synthetic-restore-drill-only@postgres:5432/senior_pomidor_drill",
  "POSTGRES_DATA_DIR=$postgresDir", "PHOTO_DATA_DIR=$photoDir",
  "ESTIMATOR_PRIVATE_DATA_DIR=$estimatorDir", "MOSQUITTO_DATA_DIR=$mosquittoDir",
  "GRAFANA_DATA_DIR=$grafanaDir", "OLLAMA_DATA_DIR=$ollamaDir",
  "LAN_BIND_ADDRESS=127.0.0.1", "POSTGRES_BIND_ADDRESS=127.0.0.1",
  "API_PUBLISHED_PORT=0", "MQTT_PUBLISHED_PORT=0", "POSTGRES_PUBLISHED_PORT=0",
  "GRAFANA_PUBLISHED_PORT=0", "OLLAMA_PUBLISHED_PORT=0", "COMPOSE_PROFILES=",
  "GRAFANA_DB_USER=restore_drill_reader", "GRAFANA_DB_PASSWORD=synthetic-restore-drill-reader-only",
  "MQTT_HOST=mosquitto", "MQTT_PORT=1883", "MQTT_USERNAME=", "MQTT_PASSWORD=",
  "PHOTO_UPLOAD_TOKEN=", "TELEMETRY_UPLOAD_TOKEN=",
  "GRAFANA_CLOUD_EXPORT_ENABLED=false", "GRAFANA_CLOUD_REMOTE_WRITE_URL=",
  "GRAFANA_CLOUD_INSTANCE_ID=", "GRAFANA_CLOUD_API_TOKEN="
)
[IO.File]::WriteAllLines($drillEnv, $drillSettings, [Text.UTF8Encoding]::new($false))
$env:POSTGRES_USER = "restore_drill"
$env:POSTGRES_DB = "senior_pomidor_drill"

docker compose --env-file $drillEnv -f docker-compose.yml -f docker-compose.dev.yml `
  -p senior-pomidor-restore-drill up -d postgres
docker compose --env-file $drillEnv -f docker-compose.yml -f docker-compose.dev.yml `
  -p senior-pomidor-restore-drill cp "$snapshot\database.dump" postgres:/tmp/database.dump
docker compose --env-file $drillEnv -f docker-compose.yml -f docker-compose.dev.yml `
  -p senior-pomidor-restore-drill exec -T postgres pg_restore --exit-on-error `
  --no-owner --no-acl --username $env:POSTGRES_USER --dbname $env:POSTGRES_DB /tmp/database.dump
```

Extract `photo_data.tar.gz`, `estimator_private_data.tar.gz`, and `mosquitto_data.tar.gz` into their
matching empty drill directories before starting the remaining services. Re-run the seven bounded
table-count queries recorded in `baseline-counts.csv`, regenerate the representative hashes from the
three restored data directories, and require exact matches before accepting the drill. Start only the
named local services; do not add a profile or the cloud exporter:

```powershell
docker compose --env-file $drillEnv -f docker-compose.yml -f docker-compose.dev.yml `
  -p senior-pomidor-restore-drill up -d --build migrate mosquitto api worker state-estimator-worker
$apiAddress = docker compose --env-file $drillEnv -f docker-compose.yml -f docker-compose.dev.yml `
  -p senior-pomidor-restore-drill port api 8000
Invoke-RestMethod "http://$apiAddress/ready"
```

Then:

1. Create a disposable Compose project name and empty volumes.
2. Restore the latest verified `database.dump` with `pg_restore` and extract the application archives.
3. Set all bind-mount paths to disposable directories and run Compose with `docker-compose.dev.yml`.
4. Compare restored counts and representative hashes with the snapshot baselines.
5. Confirm `/ready`, `/api/v1/devices`, and representative photo downloads work.
6. Stop the disposable project with the same `--env-file`, Compose files, and project name; then remove
   only its explicitly verified disposable directories. Do not add `--volumes` because named-volume
   ownership is outside this drill procedure.

Mosquitto persistence is bind-mounted from `MOSQUITTO_DATA_DIR`. Broker persistence only protects queued QoS messages when clients use durable sessions; telemetry idempotency and long-term durability remain database responsibilities.

## Data Lifecycle Dry Run

Inspect retention candidates without deleting anything:

```powershell
python -m tools.lifecycle --telemetry-retention-days 180 --photo-retention-days 180 --ai-output-dir data/ai-analysis --ai-retention-days 180
```

Optional file-tree inspection for Grafana data can be included when a host path is available:

```powershell
python -m tools.lifecycle --grafana-data-dir <grafana-data-path> --grafana-retention-days 180
```

The lifecycle tool is intentionally dry-run only. Create a fresh backup before any future destructive cleanup command is added or used.

## Host Startup And Docker Recovery

For the production Ubuntu mini-PC baseline, use [UBUNTU_HOST.md](UBUNTU_HOST.md) and the checked-in `deploy/systemd/senior-pomidor.service` unit.

Keep service policies at `restart: unless-stopped`, then make the host start Docker and this Compose project after boot.

Windows Task Scheduler example:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Set-Location 'E:\MyProjects\senior-pomidor-server'; docker compose up -d"
```

Ubuntu production uses the checked-in unit and immutable runtime layout described in [UBUNTU_HOST.md](UBUNTU_HOST.md).

Docker Desktop does not enable Docker daemon live-restore in the current local setup. Enable live-restore only on target hosts and Docker editions that explicitly support it, then test host reboot and daemon restart behavior before relying on it.

## Verification Commands

Default test suite:

```powershell
python -m pytest -q
```

Docker Compose E2E test:

```powershell
$env:RUN_DOCKER_E2E='1'
python -m pytest -q tests/test_docker_e2e.py
Remove-Item Env:RUN_DOCKER_E2E
```

If Docker Desktop is installed on Windows, start Docker Desktop and wait for the Linux engine before running the E2E test. A missing `dockerDesktopLinuxEngine` pipe means Docker is not running.

## Public GitHub Pages Status

The server can publish a sanitized outbound-only status JSON file for the `senior-pomidor-plant-v2` GitHub Pages site. The publisher intentionally excludes hostnames, ports, container IDs, paths, logs, environment variables, secrets, and raw telemetry payloads.

Preview the JSON locally:

```powershell
python -m tools.public_status --project-dir . --api-base-url http://127.0.0.1:8000
```

Write to a local file without committing:

```powershell
python -m tools.public_status --project-dir . --output .\status-preview.json
```

Recommended production flow:

1. Create a separate checkout or worktree of `senior-pomidor-plant-v2` on branch `status-data`.
2. Configure Git credentials with write access only to that repository.
3. Schedule the publisher every 5 minutes:

   ```powershell
   python -m tools.public_status --project-dir E:\MyProjects\senior-pomidor-server --pages-repo E:\MyProjects\senior-pomidor-plant-v2-status --push
   ```

The public contract is written to `status/status.json` with schema `senior-pomidor.status.v1`. GitHub Pages reads it from the `status-data` branch raw URL and treats data older than 15 minutes as stale.

## Grafana Alerts

Open provisioned alert rules:

```text
http://localhost:3000/alerting/list
```

The default alert set covers:

- device telemetry stale when `devices.last_payload_at` is older than 20 minutes for 5 minutes
- pod telemetry stale when the latest pod reading is older than 20 minutes for 5 minutes
- pod sensor errors when any pod reports errors in the last 15 minutes
- system health threshold crossings for CPU temperature, Wi-Fi RSSI, disk usage, I/O wait, pod bus voltage, and pod bus current
- system health probe errors when `system_health_jsonb.errors` appears in the last 15 minutes
- edge network failures for missing Wi-Fi profiles, disconnected Wi-Fi, failed internet reachability, and non-zero recovery exit code
- critical dry soil when an enabled pod's latest soil moisture stays below 10% for 30 minutes
- legacy raw telemetry VPD warning, stress, critical, and emergency ranges for enabled pods using `telemetry_pod_readings_flat.air_vpd_kpa`
- canonical state VPD guardrail and critical alerts using `state_snapshots.payload_jsonb #>> '{env,vpd_kpa}'`
- low canonical state confidence using `state_snapshots.payload_jsonb #>> '{quality,state_confidence}'`
- active high or critical state estimator anomalies from `anomaly_records`
- stale or missing state snapshots when telemetry is current
- edge reliability unavailable or stale for more than 20 minutes (warning, 5-minute hold)
- watchdog suppression, exhausted recovery budget, or recovery failure (critical, 1-minute hold)
- spool/disk degradation or critical state, or a spool worker error (critical, 5-minute hold)
- inactive edge application process or systemd service (critical, 1-minute hold)

The edge reliability unavailable/stale query starts from every registered device, so a missing telemetry row
still produces an alert row even though the provisioned rule uses `noDataState: OK`. Datasource execution errors
remain `Alerting`. Notification/contact-point configuration is intentionally not provisioned here.

VPD threshold ranges and operational interpretation are documented in [VPD_ALERTS.md](VPD_ALERTS.md).

## Mandatory Daily Story Manual Acceptance Test

This test is mandatory before the `llm` profile is enabled in a deployment or after changing the Ollama image,
model, prompts, generation options, scheduler, or daily-story schema. It is deliberately manual because it verifies
the real CPU/model bootstrap and generation path. Automated tests use deterministic fakes and do not replace this
acceptance gate.

Before the test, fill in `config/daily_story/environment.json` with known non-telemetry facts. Leave unknown values
as `null` rather than guessing. `running_memories.notes` may contain durable operator-curated memories; the worker
adds recent successful stories for the same node under `running_memories.previous_diary_entries` automatically.

Prerequisites:

- Docker Engine has enough disk space for `ollama/ollama:0.31.1` and the `llama3.2:3b` model.
- The selected API, PostgreSQL, MQTT, and Ollama ports are free.
- The host clock and `DAILY_STORY_TIMEZONE` are correct.
- If upload authentication is configured, include the deployment's telemetry bearer token in the seed request.

### 1. Configure a one-time due schedule

Choose a local schedule two or more minutes in the future. Model bootstrap may finish after that time; today's run
will still be picked up without backfilling an older date.

```powershell
$env:DAILY_STORY_NODE_ID='manual-story-node'
$env:DAILY_STORY_TIMEZONE='Europe/Vienna'
$env:DAILY_STORY_SCHEDULE_TIME=(Get-Date).AddMinutes(2).ToString('HH:mm')
$env:DAILY_STORY_OLLAMA_MODEL='llama3.2:3b'
$env:DAILY_STORY_OLLAMA_OPTIONS_JSON='{"temperature":0.4,"top_p":0.9,"top_k":40,"num_ctx":4096,"num_predict":2048,"repeat_penalty":1.1,"seed":42}'
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile llm up -d --build
```

The first model pull can take several minutes. Confirm PostgreSQL, API, and Ollama become healthy and model bootstrap
finishes successfully:

```powershell
docker compose --profile llm ps
docker compose --profile llm logs ollama-model-pull
```

Do not continue if `ollama-model-pull` exits non-zero or the pinned image/model cannot be fetched.

### 2. Seed one telemetry event before the scheduled minute

```powershell
$timestamp=[DateTimeOffset]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
$payload=@{
  schema_version='senior-pomidor.edge.telemetry.v2'
  device_id=$env:DAILY_STORY_NODE_ID
  timestamp_utc=$timestamp
  pods=@{
    'pod-1'=@{
      enabled=$true
      soil_moisture_percent=43.5
      air_temperature_c=23.0
      air_humidity_percent=64.0
      light_lux=12500
      errors=@()
    }
  }
  system_health=@{
    rpi_core=@{cpu_temp_c=52.0; wifi_rssi_dbm=-58.0; disk_usage_percent=31.0; io_wait_percent=1.0}
    errors=@()
  }
} | ConvertTo-Json -Depth 8
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/api/v1/edge/telemetry' -ContentType 'application/json' -Body $payload
```

If `TELEMETRY_UPLOAD_TOKEN` is set, add
`-Headers @{Authorization="Bearer $env:TELEMETRY_UPLOAD_TOKEN"}` to `Invoke-RestMethod`.

### 3. Wait for the run and retrieve it through the public API

After the scheduled minute and successful model bootstrap, inspect worker health and logs:

```powershell
docker compose --profile llm ps daily-story-worker
docker compose --profile llm logs --tail 100 daily-story-worker
$story=Invoke-RestMethod "http://127.0.0.1:8000/api/v1/daily-stories/latest?node_id=$env:DAILY_STORY_NODE_ID"
$story | ConvertTo-Json -Depth 5
```

The test passes only when all of the following are true:

- `daily-story-worker` is healthy and the returned status is `succeeded`.
- `story_date` is today's date in `DAILY_STORY_TIMEZONE`; no record was created for an older date.
- `story` is at least 1680 characters, first-person, grounded in the seeded data, and no longer than 32768 characters.
- `node_id`, model, UTC window, and generation timestamp are present and correct.
- A range request returns the same run:

  ```powershell
  Invoke-RestMethod "http://127.0.0.1:8000/api/v1/daily-stories/range?node_id=$env:DAILY_STORY_NODE_ID&limit=30"
  ```

- The API object contains only `run_id`, `node_id`, `story_date`, `window_start_utc`, `window_end_utc`, `status`,
  `story`, `model`, and `generated_at_utc`. It must not expose prompts, environment context, input summaries, Ollama
  options, runtime internals, or error details.
- Restarting the worker does not create a second `(node_id, story_date)` record:

  ```powershell
  docker compose restart daily-story-worker
  Invoke-RestMethod "http://127.0.0.1:8000/api/v1/daily-stories/range?node_id=$env:DAILY_STORY_NODE_ID&limit=30"
  ```

Record the deployment identifier, image/model digest, test date, returned run ID, result, and operator name in the
deployment change record. A `failed`, `skipped_no_data`, duplicate, oversized, ungrounded, or private-field-leaking
result fails acceptance and must be resolved before enabling the profile for scheduled use.

For a disposable test project, stop it after recording evidence. Add `--volumes` only when the PostgreSQL and Ollama
volumes are explicitly disposable:

```powershell
docker compose --profile llm down
```

## Useful Read API Calls

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/devices
Invoke-RestMethod http://localhost:8000/api/v1/devices/latest
Invoke-RestMethod "http://localhost:8000/api/v1/devices/pi-001/telemetry?since_hours=24&limit=100"
Invoke-RestMethod "http://localhost:8000/api/v1/devices/pi-001/photos?limit=25"
Invoke-RestMethod "http://localhost:8000/api/v1/photos/recent?limit=12"
Invoke-RestMethod "http://localhost:8000/api/v1/state/latest?node_id=pi-001"
Invoke-RestMethod "http://localhost:8000/api/v1/sensor-health/latest?node_id=pi-001"
Invoke-RestMethod "http://localhost:8000/api/v1/anomalies/active?node_id=pi-001"
```

## Offline AI Analysis Prototype

Issue 8 is implemented as an offline consumer only. The analysis tool reads stored photos and matching telemetry from the database, calls a local Ollama vision model from a separate process, and appends JSONL report records under `data/`. It is not part of `/api/v1/edge/telemetry`, `/api/v1/edge/photos`, API startup, or the MQTT worker.

Install Ollama separately and pull the default local vision model:

```powershell
ollama pull llama3.2-vision
```

Preview selected photos, matched telemetry events, and prompt inputs without calling the model:

```powershell
python tools/analyze_recent_photos.py --dry-run --limit 5 --telemetry-window-minutes 30
```

Run analysis and append JSONL output:

```powershell
python tools/analyze_recent_photos.py --limit 5 --output data/ai-analysis/results.jsonl
```

Useful overrides:

```powershell
$env:AI_ANALYSIS_MODEL='llama3.2-vision'
$env:OLLAMA_HOST='http://localhost:11434'
python tools/analyze_recent_photos.py --device-id pi-001 --since-hours 24 --timeout-seconds 180
```

Prompt inputs are intentionally limited to stored Core data:

- photo metadata: `photo_id`, `device_id`, `captured_at_utc`, `sharpness_score`, content type, size, and SHA-256
- nearby telemetry from the same device within the configured capture-time window
- pod readings, pod errors, system health, and derived health alerts
- the JPEG file referenced by the photo metadata row

Each JSONL record includes the photo identity, model, analysis timestamp, matching telemetry event IDs, prompt inputs, model response text, runtime details, and a nullable `error` field. Per-photo failures are written as report records so a bad image or unavailable model does not hide which inputs were selected.

Operational cost for the default path is zero external API spend because analysis runs against local Ollama. The real cost is local CPU/GPU time, memory pressure, and wall-clock runtime; keep `--limit` small until the model performance is known on the deployment machine.
