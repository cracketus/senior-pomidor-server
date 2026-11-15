# Season 2026 — Core data freeze and production shutdown

**Status: OPERATOR RUNBOOK, NOT EXECUTION EVIDENCE.**
Production target: Ubuntu source-free `/srv/apps/senior-pomidor/app`, root-owned `senior-pomidor.service`. Verify the *actual* host/deployment before doing anything. Companion: [Edge winterization](https://github.com/cracketus/senior-pomidor-plant-v2/blob/main/docs/SEASON_SHUTDOWN_2026.md); season manifest owner: [programme hub](https://github.com/cracketus/senior-pomidor/blob/main/docs/SEASON_2026_CLOSEOUT.md).

## Objective and boundaries

Freeze the 2026 observation stream while preserving historic PostgreSQL, photos, private estimator JSONL, MQTT state, checksum manifests, historical Grafana views and replay/research access.

The Core Compose project owns `api`, `worker`, `state-estimator-worker`, `mosquitto`, and optional `grafana-cloud-exporter` / `daily-story-worker`. **Platform PostgreSQL, Grafana, Ollama and the Docker network are independently owned** and MUST remain running for other consumers. The `senior-pomidor.service` production unit uses Compose `stop` (not `down -v`). Do not change a shared platform `systemd` unit, DB, global backup timer, firewall or Docker network as a side effect.

## 0. Preconditions and irreversible boundaries

1. Physically verify irrigation/actuators are safe OFF; disable any remote or autonomous control path.
2. Announce a season end timestamp (`Europe/Vienna` + UTC), responsible operator, Core and Edge revisions, current dataset coverage and manifest location. Distinguish final *observation* time from final *ingestion* time: late spool replay can extend ingestion after sampling ceased.
3. Core must remain online until the Edge maintainer confirms queue state and required final uploads. Any intentionally undelivered spool or photos must be recorded with copies/checksums. Do not discard data to obtain a zero backlog.
4. Identify any other data producers (simulators, staging Edge, replay jobs, cron, HTTP photo clients) and ensure they will not target production after shutdown. Staging must remain isolated.
5. Check backup storage availability and current `senior-pomidor.service` status. Never run `docker compose down -v`, `docker volume prune`, truncate tables, or delete photos/logs.

## 1. Confirm live production identity

```bash
sudo systemctl --no-pager --full status senior-pomidor.service
sudo systemctl list-timers --all | grep 'senior-pomidor' || true
cd /srv/apps/senior-pomidor/app
sudo docker compose --env-file /srv/secrets/senior-pomidor/runtime.env \
  -f docker-compose.yml -f docker-compose.prod.yml ps
```

Record current `APP_IMAGE` digest/release identity and observed running profiles (including optional story/exporter). Do not echo `runtime.env`, DB credentials, tokens or host topology into public artifacts.

## 2. Final verified backup before shutdown

With Edge drained/stopped and Core running, use the **production** backup entry point; source-checkout `python -m tools.backup` is *not* packaged in this runtime:

```bash
sudo systemctl start senior-pomidor-backup@weekly.service
sudo systemctl --no-pager --full status senior-pomidor-backup@weekly.service
sudo journalctl -u senior-pomidor-backup@weekly.service -n 100 --no-pager
```

Weekly backups include a logical PostgreSQL dump, photo storage, estimator private logs and MQTT state, unlike daily DB-only snapshots. Check the resulting dated backup set and `SHA256SUMS`; independently copy the complete set to encrypted off-host storage. **Verify the copy/restore in a disposable isolated environment before describing the archive as recoverable.** Backup is not complete just because `systemctl start` returned. A weekly backup can temporarily stop and restart *application writers*, therefore it belongs before the final Core stop.

Take the final dataset baseline through a read-only PostgreSQL session with the platform administrator's approved connection method. Candidate tables documented in `docs/OPERATIONS.md`: `telemetry_events`, `pod_readings`, `pod_errors`, `photos`, `state_snapshots`, `sensor_health_snapshots`, `anomaly_records`, `estimator_diagnostics`. Record row counts and latest observation timestamps by node/pod; do not assume `ingested_at` or other column names without inspecting the schema. Preserve last known Grafana screenshots/links, outage periods and excluded/uncertain data windows.

## 3. Stop application-owned data producers, including automatic restart

```bash
sudo systemctl disable --now senior-pomidor.service
sudo systemctl disable --now senior-pomidor-backup-daily.timer senior-pomidor-backup-weekly.timer
sudo systemctl is-active senior-pomidor.service || true
sudo systemctl is-enabled senior-pomidor.service || true
cd /srv/apps/senior-pomidor/app
sudo docker compose --env-file /srv/secrets/senior-pomidor/runtime.env \
  -f docker-compose.yml -f docker-compose.prod.yml ps -a
```

Verify `api`, `worker`, `state-estimator-worker`, `mosquitto`, `grafana-cloud-exporter` and `daily-story-worker` are no longer running. If a separately started Compose project or profile is still active, identify it first and stop it **only within the Senior Pomidor project**, rather than stopping the shared platform. Disable/inspect any additional application-specific timers, scheduled tasks and external exporters/agents.

Stopping **only Edge is insufficient**: state-estimator and optional daily story can continue writing on their own; photo HTTP ingestion can still accept writes. Leaving `api` on is not a guarantee of read-only mode: `GET /api/v1/state/latest` has historically supported lazy state generation. For this season the safest freeze is to stop the application Compose project while retaining platform PostgreSQL and Grafana. A genuinely read-only historical API is future engineering work.

## 4. Freeze verification and Grafana

Using the **platform PostgreSQL** read-only connection, compare the recorded baseline counts after 10–15 minutes, and once again after any automation/scheduled job boundary. Confirm no 2026 production telemetry, photos, canonical states or story records were inserted. Investigate any growth: late replay, staging connected to production, automation or a still-running container. This is a *criterion*, not an assertion about current host state.

Keep platform Grafana, PostgreSQL, Ollama, other containers, volumes, secrets and routine platform backups intact. Change only Senior Pomidor-specific Grafana alert rules/notification routing so intentional stale sensors don't generate incidents; do not silence shared alerts. Historical charts should use an explicit **2026 season** time range rather than default “last 24 h”, and labels should say `ARCHIVED — 2026 season`, not `healthy`/live.

If production feeds a public website or Grafana Cloud, show `Season 2026 completed` and a last-observation timestamp. Stop export workers; preserve historical public data only after privacy review. Remove or invalidate any public URL that misleadingly reports fresh live measurements. Never publish credentials, exact private coordinates, home-network data or unreviewed photographs.

## 5. Archive / long-term preservation

Link immutable, checksummed private artifacts:
- production Core/Edge release or commit + config **fingerprints** (never raw secrets);
- data-range and node/pod/sensor identity + calibration history;
- database dump, photos, JSONL, MQTT state, Edge spool archive and any unresolved queue;
- watchdog/availability incident evidence, known gaps, manual interventions with evidence;
- baseline summary and proposed sanitized replay subset.

Programme research consolidation belongs to [server #302](https://github.com/cracketus/senior-pomidor-server/issues/302). Retention jobs are intentionally disabled above to stop new seasonal writes, so protect the frozen archive with independent encrypted off-host copies. Verify backup and restore before any later migration/reorganization.

## Acceptance / restart gate

- [ ] Verified last observation vs last ingestion timestamps and captured counts.
- [ ] All Edge producers stopped and pending queue documented.
- [ ] Final weekly Core backup complete, checksummed and copied off host; isolated restore rehearsal recorded.
- [ ] Senior Pomidor app unit and scheduled backup timers disabled/inactive; no app-owned containers running.
- [ ] No new telemetry/state/photo/story database records in repeated read-only count checks.
- [ ] Platform PostgreSQL/Grafana/Ollama and unrelated services unaffected.
- [ ] Alerting and public site reflect **archived**, not live status.
- [ ] Season manifest and operator sign-off recorded.

**Recommissioning**: use staging/compatibility gates; compare 2027 Edge/Core contracts and calibrations, explicitly re-enable only approved services, scheduled backups and seasonal alert rules. A casual server reboot or Docker daemon restart must not silently resume production.
