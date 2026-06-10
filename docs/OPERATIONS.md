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
```

MQTT should be treated as the primary path. HTTP telemetry is the compatibility fallback.

## Backup And Restore

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

## Useful Read API Calls

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/devices
Invoke-RestMethod http://localhost:8000/api/v1/devices/latest
Invoke-RestMethod "http://localhost:8000/api/v1/devices/pi-001/telemetry?since_hours=24&limit=100"
Invoke-RestMethod "http://localhost:8000/api/v1/devices/pi-001/photos?limit=25"
Invoke-RestMethod "http://localhost:8000/api/v1/photos/recent?limit=12"
```
