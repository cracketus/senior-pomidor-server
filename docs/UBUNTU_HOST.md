# Ubuntu production host

Production runs a source-free release bundle. Senior Pomidor owns its application data and
containers; PostgreSQL, Grafana, and Ollama are platform services managed independently under
`/srv/docker` and `/srv/data`. Stopping, upgrading, or removing the Senior Pomidor Compose project
must never affect those shared services.

| Purpose | Path |
| --- | --- |
| Active release symlink | `/srv/apps/senior-pomidor/app` |
| Root-controlled releases / incoming assets | `/srv/apps/senior-pomidor/releases` / `.incoming` |
| Public photos / private MQTT state | `/srv/apps/senior-pomidor/data/public/photos` / `data/private/mosquitto` |
| Runtime secret | `/srv/secrets/senior-pomidor/runtime.env` |
| Daily, weekly, migration backups | `/srv/backups/senior-pomidor/{daily,weekly,migration}` |
| Private estimator logs | `/srv/logs/senior-pomidor/estimator-private` |
| Root-owned automation | `/srv/automation/scripts/senior-pomidor` |

Legacy app-local `backups`, `secrets`, and `logs` directories are unused. Provisioning deliberately
leaves any existing copies untouched.

## Platform onboarding

The platform administrator must first create the external `srv-platform` network and independently
deploy PostgreSQL, Grafana, and Ollama under `/srv/docker` with persistent state under `/srv/data`.
PostgreSQL must expose DNS name `postgres` on that network and have a `senior_pomidor` database plus
dedicated application role. Ollama must expose DNS name `ollama`; provision the configured story
model before enabling the optional `daily-story` application profile.

Create Grafana's read-only role/grants using `docker/postgres/init-grafana-reader.sh` as platform
onboarding, not during application startup or restore. Store its credential in
`/srv/secrets/grafana/senior-pomidor.env` (root-owned mode `0600`) and configure the platform Grafana
provisioning from `docker/grafana/provisioning`. Never place Grafana credentials in Senior
Pomidor's runtime environment.

## Provision and install

Install Docker Engine and the Compose plugin, then run from the extracted runtime bundle:

```bash
sudo ./scripts/provision-host.sh
sudo install -o root -g root -m 0600 senior-pomidor.env.example \
  /srv/secrets/senior-pomidor/runtime.env
sudoedit /srv/secrets/senior-pomidor/runtime.env
```

Set `DATABASE_URL` for platform PostgreSQL and also set `POSTGRES_HOST`, `POSTGRES_PORT`, database,
user, and password for readiness, backup, and restore. Keep `PLATFORM_DOCKER_NETWORK=srv-platform`.
Normal production uses `COMPOSE_PROFILES=cloud-export`; add `daily-story` only after its model exists.
The host account is intentionally not in the Docker group; systemd performs root-owned orchestration.

Download release assets to `/srv/apps/senior-pomidor/releases/.incoming`, then install and enable:

```bash
sudo /srv/automation/scripts/senior-pomidor/install-release.sh \
  senior-pomidor-runtime-vX.Y.Z.tar.gz senior-pomidor-runtime-vX.Y.Z.tar.gz.sha256
sudo systemctl enable --now senior-pomidor.service
sudo systemctl enable --now senior-pomidor-backup-daily.timer \
  senior-pomidor-backup-weekly.timer
```

Releases and configuration are root-owned and not writable by `senior-pomidor`. Never deploy
`latest`. Verify with:

```bash
systemctl status senior-pomidor
cd /srv/apps/senior-pomidor/app
sudo docker compose --env-file /srv/secrets/senior-pomidor/runtime.env \
  -f docker-compose.yml -f docker-compose.prod.yml ps
curl -fsS "http://${NEW_SERVER_LAN_IP}:8000/ready"
```

## One-time handoff from the earlier draft layout

Provisioning does not move existing secrets or backups. If the temporary app-local draft paths
exist, copy and verify them explicitly as root, then leave the originals untouched until an
independent recovery test succeeds:

```bash
sudo install -o root -g root -m 0600 \
  /srv/apps/senior-pomidor/secrets/senior-pomidor.env \
  /srv/secrets/senior-pomidor/runtime.env
sudo sha256sum /srv/apps/senior-pomidor/secrets/senior-pomidor.env \
  /srv/secrets/senior-pomidor/runtime.env

sudo cp -a /srv/apps/senior-pomidor/backups/. \
  /srv/backups/senior-pomidor/migration/
sudo find /srv/backups/senior-pomidor -type d -exec chown root:root {} + -exec chmod 0700 {} +
sudo find /srv/backups/senior-pomidor -type f -exec chown root:root {} + -exec chmod 0600 {} +
```

## Backups and recovery

Daily sets contain logical database dumps; weekly sets also contain photos, estimator logs, and
MQTT state. Secrets and shared PostgreSQL/Grafana filesystem state are never archived. Restore only
accepts a checksummed set beneath `/srv/backups/senior-pomidor/migration`, requires empty app-owned
targets, and refuses a database that already contains user tables. Legacy `grafana.tar.gz` is
reported and ignored.

`SHA256SUMS` detects local corruption; it does not authenticate a backup after off-host transfer.
Maintain a separately encrypted off-host copy and store its encryption key outside
`/srv/backups`. Test restores regularly without touching shared-service storage.

Restrict LAN access to API `8000` and MQTT `1883` using both host firewall policy and Docker's
`DOCKER-USER` chain. Platform PostgreSQL, Grafana, and Ollama exposure is governed by the platform
runbook and must not be widened by this application.
