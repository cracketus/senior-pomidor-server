# Windows-to-Ubuntu migration runbook

This is a 30–60 minute cold cutover to migration `0008_story_environment`. Preserve the stopped
Windows installation unchanged for at least seven days. Ollama remains disabled.

## Prepare and baseline

- Provision and firewall Ubuntu using [UBUNTU_HOST.md](UBUNTU_HOST.md). Confirm the tagged image is
  anonymously pullable and record its digest. Copy secrets directly into
  `/srv/secret/senior-pomidor.env`; never put `.env` in Git, a release, or a migration archive.
- Resolve the existing unhealthy state-estimator condition or record its understood cause and
  accepted impact before migration.
- Immediately before rehearsal and cutover, record the Windows commit/image digest, service health,
  `SELECT version_num FROM alembic_version`, `pg_database_size`, table counts, photo/file counts, and
  representative photo SHA-256 values. Earlier observations (about 117 MB, 30,705 telemetry events,
  61,410 pod readings, 95 photos, 2,193 state snapshots, and 57 anomalies) are context only.
- Record sanitized Compose service/image inventory. Do not capture expanded environment output.

Useful database baseline query:

```sql
SELECT 'telemetry_events', count(*) FROM telemetry_events
UNION ALL SELECT 'pod_readings', count(*) FROM pod_readings
UNION ALL SELECT 'photos', count(*) FROM photos
UNION ALL SELECT 'state_snapshots', count(*) FROM state_snapshots
UNION ALL SELECT 'sensor_health_snapshots', count(*) FROM sensor_health_snapshots
UNION ALL SELECT 'anomaly_records', count(*) FROM anomaly_records
UNION ALL SELECT 'estimator_diagnostics', count(*) FROM estimator_diagnostics
ORDER BY 1;
```

## Rehearsal

1. Take a preliminary Windows migration set. Restore it into dedicated rehearsal directories, not
   the production bind mounts. Override all `*_DATA_DIR` variables and bind API/MQTT to loopback or
   alternate ports. Keep `GRAFANA_CLOUD_EXPORT_ENABLED=false` to prevent duplicate export.
2. Initialize PostgreSQL with the new role, restore the custom dump with `pg_restore --no-owner
   --no-acl`, and restore archives with numeric ownership. Expected image UIDs are PostgreSQL `70`,
   Grafana `472`, and Mosquitto `1883`; verify them against the pinned images before applying chown.
3. Run `docker compose run --rm migrate`. Require the exact Alembic result
   `0008_story_environment`, then run the Grafana-reader initialization script again.
4. Verify `/ready`, baseline row/file counts, representative photo checksums and API retrieval,
   Grafana datasource/dashboard/alerts, real MQTT ingestion, and new state-estimator output. Diagnose
   every unhealthy container before scheduling cutover.

## Final Windows migration set

After stopping edge telemetry/photo processes, wait several minutes and prove counts no longer
change. Stop API, MQTT worker, state estimator, Cloud exporter, and Grafana, leaving PostgreSQL up.
Create:

```powershell
.\tools\backup_data.ps1 -Mode migration -BackupRoot D:\senior-pomidor-backups `
  -ProjectName senior-pomidor-server
```

- `database.dump`: `pg_dump --format=custom --no-owner --no-acl`;
- `globals-audit.sql`: `pg_dumpall --globals-only --no-role-passwords` for audit only (do not
  restore old roles or archive their password verifiers);
- `photos.tar.gz`, `estimator-private.tar.gz`, `grafana.tar.gz`, `mosquitto.tar.gz`, preserving
  numeric ownership;
- baseline counts, representative photo checksums, and sanitized configuration/image inventory;
- `SHA256SUMS` covering every other artifact.

Verify `sha256sum --check SHA256SUMS`, then stop the remaining Windows Compose services. Do not run
`down -v`, remove containers/images, or alter the working directory. Transfer into a timestamped
`/srv/backups/senior-pomidor/migration-*` directory and verify checksums again on Ubuntu.

## Cold cutover

1. Announce the outage; stop every edge node; confirm no new telemetry/photos arrive.
2. Install the tagged runtime bundle with `/srv/automation/install-release.sh`. `APP_IMAGE` must be
   the matching GHCR version tag or recorded digest. Do not use `latest`.
3. Ensure the five target data/media/log directories are empty. Run:

   ```bash
   sudo /srv/automation/restore-migration.sh \
     /srv/backups/senior-pomidor/migration-<timestamp>
   ```

   This verifies checksums, initializes PostgreSQL with new credentials, restores without old
   ownership/ACLs, restores the four archives, migrates once, checks
   `0008_story_environment`, and reapplies Grafana reader grants.
4. Start and validate Ubuntu before changing any edge:

   ```bash
   sudo systemctl start senior-pomidor
   systemctl status senior-pomidor
   cd /srv/apps/senior-pomidor/current && docker compose ps
   curl -fsS "http://${NEW_SERVER_LAN_IP}:8000/health"
   curl -fsS "http://${NEW_SERVER_LAN_IP}:8000/ready"
   ```

5. Change every Raspberry Pi's MQTT host, HTTP telemetry URL, and photo URL to the new LAN address;
   preserve tokens and contracts. Start one node, verify fresh MQTT telemetry plus one photo upload,
   then start the rest. Monitor at least one complete telemetry/photo cycle.

## Acceptance

- All enabled containers and systemd are healthy; `/health` and `/ready` succeed.
- Restored counts/files equal the final Windows baseline before ingestion and only increase after.
- Representative restored photos retain SHA-256 values and are retrievable through the API.
- MQTT telemetry, HTTP telemetry, and photo upload pass from a real edge node.
- Grafana login, datasource, dashboards, and alerts work; Cloud exporter logs successful writes.
- The state estimator creates fresh snapshots with no unexplained unhealthy status.
- PostgreSQL is unreachable from another LAN host.
- A full server reboot restores the stack without manual Docker commands.

## Backup and restore operations

The installed timers create daily custom database dumps retained 30 days and weekly archives of
photos, Grafana, estimator logs, and Mosquitto retained 8 weeks. Every set includes verified
checksums under `/srv/backups/senior-pomidor`. The weekly job briefly stops file-writing services so
the database and archives form a consistent set, then restarts them even if archiving fails. Review timer results with `systemctl list-timers` and
`journalctl -u 'senior-pomidor-backup@*'`.

Monthly, restore the newest sets into isolated directories/project names with Cloud export disabled;
verify migration, counts, photos, and readiness, then record the result. Backups on this server do
not protect against loss of its disk; copy verified sets to separately administered storage if that
risk is unacceptable.

## Rollback

Before Ubuntu accepts edge traffic, restart Windows and retain or restore the old edge configuration.
After Ubuntu accepts traffic, prefer a forward fix. Emergency host rollback requires stopping all
edges, taking a fresh Ubuntu database/media backup, repointing edges to Windows, and retaining Ubuntu
data for reconciliation. Never downgrade Alembic or delete either host's volumes.

Application-only rollback means atomically switching `current` to a previously verified immutable
release and reloading systemd, but only after confirming that image supports the current database
schema.
