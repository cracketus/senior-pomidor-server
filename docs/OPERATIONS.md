# Senior Pomidor Server Operations

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

5. Start infrastructure and apply migrations:

   ```powershell
   docker compose up -d postgres mosquitto
   docker compose run --rm api alembic upgrade head
   docker compose up -d api worker
   ```

6. Verify service health:

   ```powershell
   Invoke-RestMethod http://localhost:8000/health
   docker compose ps
   docker compose logs --tail 100 api
   docker compose logs --tail 100 worker
   docker compose run --rm api alembic current
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

Create a backup directory outside the repository:

```powershell
New-Item -ItemType Directory -Force backups
```

Back up PostgreSQL:

```powershell
docker compose exec -T postgres pg_dump -U senior_pomidor senior_pomidor > backups\senior_pomidor.sql
```

Back up uploaded photos:

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

## Grafana Alerts

Open provisioned alert rules:

```text
http://localhost:3000/alerting/list
```

The default alert set covers:

- device telemetry stale when `devices.last_payload_at` is older than 10 minutes for 5 minutes
- pod telemetry stale when the latest pod reading is older than 10 minutes for 5 minutes
- pod sensor errors when any pod reports errors in the last 15 minutes
- system health threshold crossings for CPU temperature, Wi-Fi RSSI, disk usage, I/O wait, pod bus voltage, and pod bus current
- system health probe errors when `system_health_jsonb.errors` appears in the last 15 minutes
- critical dry soil when an enabled pod's latest soil moisture stays below 10% for 30 minutes
- VPD warning, stress, critical, and emergency ranges for enabled pods using `air_vpd_kpa`

VPD threshold ranges and operational interpretation are documented in [VPD_ALERTS.md](VPD_ALERTS.md).

## Useful Read API Calls

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/devices
Invoke-RestMethod http://localhost:8000/api/v1/devices/latest
Invoke-RestMethod "http://localhost:8000/api/v1/devices/pi-001/telemetry?since_hours=24&limit=100"
Invoke-RestMethod "http://localhost:8000/api/v1/devices/pi-001/photos?limit=25"
Invoke-RestMethod "http://localhost:8000/api/v1/photos/recent?limit=12"
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
