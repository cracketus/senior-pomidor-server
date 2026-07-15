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
PostgreSQL --> optional Grafana Cloud exporter with sanitized low-cardinality raw telemetry metrics
```

The API, MQTT broker, PostgreSQL port, dashboard, and Grafana UI are intended for trusted LAN use. For any remote access, put the service behind a VPN, firewall allow-list, or reverse proxy with authentication and TLS.

## Release Checklist

Before tagging or publishing a server release:

- Run `python -m pytest -q`.
- Run `nox -s lint format_check types security`.
- Run `nox -s deps_audit`.
- Run `$env:RUN_DOCKER_E2E='1'; python -m pytest -q tests/test_docker_e2e.py` when Docker is available.
- Verify `GET /health` and `GET /ready` after `docker compose up -d --build`.
- Confirm there are no local `.env`, private key, known-hosts, `.db`, `data/`, or `backups/` files in the release checkout.
- Confirm `.env.example` still uses local bootstrap defaults only, and document any required production overrides.
- Verify `python -m tools.edge_readiness --api-base-url http://127.0.0.1:8000 --mqtt-host 127.0.0.1 --photo-storage-dir data/photos`.
- Verify `tools/backup_data.ps1` can write a backup outside the repository.
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
   docker compose up -d --build
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
   docker compose up -d --build --force-recreate
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
   Confirm the dashboard includes the raw telemetry panels plus `Latest State Summary`, `Canonical Env VPD`, `State Confidence`, `Average Soil Moisture`, `Latest Sensor Health Summary`, and `Active Anomalies`.

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

For longer-term sizing, retention, power estimates, and pod-count expansion
planning, see [CAPACITY_PLANNING.md](CAPACITY_PLANNING.md).
For public export boundaries, see [PUBLIC_DATA_POLICY.md](PUBLIC_DATA_POLICY.md).

Create timestamped backups outside the repository:

```powershell
.\tools\backup_data.ps1 -BackupRoot D:\senior-pomidor-backups
```

Recommended schedule:

- Daily PostgreSQL backup.
- Weekly photo archive.
- Fresh backup before Docker image, schema, or host OS upgrades.
- Investigate disk usage at 70%; uploaded photos are the primary growth risk.

Manual PostgreSQL backup:

```powershell
docker compose exec -T postgres pg_dump -U senior_pomidor senior_pomidor > backups\senior_pomidor.sql
```

Manual uploaded photo backup:

```powershell
docker run --rm -v senior-pomidor-server_photo_data:/data -v ${PWD}\backups:/backup alpine tar czf /backup/photo_data.tgz -C /data .
```

Restore PostgreSQL into an empty database:

```powershell
Get-Content backups\senior_pomidor.sql | docker compose exec -T postgres psql -U senior_pomidor senior_pomidor
```

Restore uploaded photos:

```powershell
docker run --rm -v senior-pomidor-server_photo_data:/data -v ${PWD}\backups:/backup alpine sh -c "cd /data && tar xzf /backup/photo_data.tgz"
```

Verify photo metadata and files agree:

```powershell
python tools/check_photo_storage.py
```

Restore drill:

1. Create a disposable Compose project name and empty volumes.
2. Restore the latest SQL dump and photo archive into that project.
3. Run `docker compose -p <temporary-project> up -d --build`.
4. Confirm `/ready`, `/api/v1/devices`, and representative photo downloads work.
5. Remove the disposable project with `docker compose -p <temporary-project> down -v`.

Mosquitto persistence is mounted at `mosquitto_data:/mosquitto/data`. Broker persistence only protects queued QoS messages when clients use durable sessions; telemetry idempotency and long-term durability remain database responsibilities.

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

Linux systemd example:

```ini
[Unit]
Description=Senior Pomidor Compose stack
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
WorkingDirectory=/opt/senior-pomidor-server
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

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

VPD threshold ranges and operational interpretation are documented in [VPD_ALERTS.md](VPD_ALERTS.md).

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
