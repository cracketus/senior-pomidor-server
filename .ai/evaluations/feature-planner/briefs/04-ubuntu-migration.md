# Implementation Brief: Windows-to-Ubuntu migration

Status: draft

Planner/version: Feature Planner 1.1
Issue/decision: Historical fixture FP-04

## Problem

Application data and service ownership must move from Windows to Ubuntu with minimal loss and reversible cutover; target topology and restore evidence are not yet approved.

## Desired outcome

An immutable candidate is restored and validated in an isolated Ubuntu rehearsal, then cut over with preserved source, bounded downtime and tested rollback.

## Current behavior and evidence

`docs/OPERATIONS.md`, `docker-compose.yml` and `tools/backup_data.ps1` describe the pre-migration operations available to the fixture. Target paths, platform services, final data volume and recovery point are Unknown.

## Scope

- Inventory, checksummed logical/app-data backup, explicit rehearsal isolation/restore, validation, cold cutover, rollback and evidence bundle.

## Out of scope

- Destructive source cleanup, automatic deployment, copying secrets in backup, lifecycle-managing unrelated platform services.

## Architecture placement

Application release/data remain application-owned; PostgreSQL/Grafana/Ollama ownership on target must be explicitly approved before scripts are designed.

## Affected contracts and consumers

Deployment env, Compose topology, database/photo/private paths and edge endpoints are affected. API/MQTT schemas should remain unchanged; compatibility must be replayed.

## Safety/risk classification

Classes: `infrastructure_deployment`, `schema_data_contract`. Flags: `data_loss_migration`, `production_availability`, `security_secrets`, `edge_server_compatibility`. Apply `SP-FAIL-003`, `SP-FAIL-004`, `SP-FAIL-005`.

## Proposed implementation sequence

1. Approve target ownership/paths/versions and rollback RPO/RTO.
2. Build immutable candidate and secret-separated checksummed backup.
3. Restore to isolated project, credentials, paths, network and loopback ports with Grafana Cloud/external export disabled.
4. Compare migrations/counts/photo hashes/API/MQTT/worker health; test application stop without shared-service impact.
5. Freeze writers, take final set, cut over canary edge nodes, then monitor.

## Failure modes

Checksum mismatch, incomplete backup, non-empty target, migration/readiness failure, path divergence, permission error, duplicate export, edge endpoint lag and post-cutover writes require abort/rollback.

## Backward compatibility

Retain Windows source unchanged through the rollback window; preserve schemas and accept existing edge payloads during endpoint transition.

## Testing plan

Baseline/Compose/release tests; isolated restore with counts/hashes and failure injection; manual permissions, network, edge canary and shared-platform checks.

## Observability

Evidence bundle records artifact hashes, versions, counts, readiness, worker freshness and sanitized errors in UTC plus Europe/Vienna operator timeline.

## Documentation updates

Create target host, rehearsal, cutover/rollback and secret-handling runbooks.

## Rollout and rollback

Abort before DNS/edge switch on any rehearsal failure. After cutover, stop only target application, return endpoints to preserved Windows, restart writers and reconcile boundary data.

## Acceptance criteria

- [ ] Isolated restore matches checksums/counts/representative photos and passes ingestion/readiness without external export.
- [ ] Rehearsed rollback preserves source and does not stop shared platform services.

## Blocking open questions

- Target topology/versions/paths/owners, downtime/RPO/RTO, data size, edge endpoint switch and off-host backup custody?

## Evidence and references

- `docs/OPERATIONS.md`; `docker-compose.yml`; `tools/backup_data.ps1`.
- Target production facts and restore success are unverified.
