# Implementation Brief: v0.3.1 production qualification and Edge/Core reliability fixes

Status: draft

Planner/version: Codex / 2026-09-13

Approver/date: pending human approval

Issue/decision: #357; admin CLI for lifecycle, two linked Core/Edge PRs, full qualification via #248

Agent run ID / audit artifact: not assigned

## Problem

Observed in production after Core `v0.3.0`:

- MQTT worker is Docker-healthy and accepts telemetry, but API reports `worker_health_missing` because API and worker use isolated `/tmp` paths.
- A historical `pi-001` remains in the device table with stale telemetry and active anomalies. The operator aggregate has no lifecycle state and reports global `STALE/ALERT`.
- Fresh Docker Edge telemetry has `process_running=true` but no `service_manager=none`; Core correctly reports the ambiguous application state as `UNKNOWN`.
- Edge spool metadata retains `last_error_code=ack_record_id_mismatch` after later successful/duplicate delivery.
- Staging scenario commands return `NOT_RUN`; they are not evidence of compatibility. Full cross-repository execution is tracked by #248.

The first two items are confirmed Core/Compose integration and data-lifecycle gaps. The application-health item requires the coordinated Edge release. ACK metadata behavior is confirmed in the Edge implementation and requires an Edge PR.

## Desired outcome

For v0.3.1, a fresh active Edge and healthy worker produce deterministic `OK/FRESH` health signals, while decommissioned devices remain readable without affecting active-fleet aggregates. Successful delivery leaves no current ACK error. Core and Edge are qualified as one immutable pair.

## Current behavior and evidence

- Core image under test: `ghcr.io/cracketus/senior-pomidor-server@sha256:5c9f82606bfd499e894fbd8e5a99dfaccb23843f6d9ca1477d5151e0ac194e3e`.
- Core revision under test: `549dc4d21897203c167749611416355f820d6372`.
- `/ready` and `/health` pass; MQTT worker is healthy and accepts telemetry.
- `balcony-edge-01` sends fresh telemetry; watchdog is healthy and spool counts are zero.
- `pi-001` telemetry is stale and has active `REQUIRED_SENSOR_UNAVAILABLE` and `LOW_STATE_CONFIDENCE` anomalies.
- `docker-compose.yml` sets worker health to `/tmp/senior-pomidor-worker-health.json` and does not mount that path into API.
- `app/health_summary.py` reads the configured path locally and returns `worker_health_missing` when absent.
- `OperatorSummaryService` selects all `Device` rows and aggregates active anomalies without lifecycle filtering.
- Edge `complete_attempt()` clears per-record error state on successful/duplicate delivery but does not clear aggregate `last_delivery_error_*` metadata.
- Related cross-repository work: server #248 and #250; Edge release-validation epic #97.

## Scope

- Add additive device lifecycle storage with `ACTIVE` and `DECOMMISSIONED`.
- Add a human-operated, idempotent lifecycle admin CLI; do not add a production write HTTP endpoint.
- Preserve historical telemetry, state, anomaly and photo rows.
- Exclude decommissioned devices from active-fleet State Estimator, operator aggregate, anomaly aggregate, Grafana/public active-fleet views, while retaining device-specific reads.
- Share worker health through a project-scoped named Compose volume; API read-only, worker read-write.
- Make health-file writes atomic and retain fail-safe missing/malformed/stale behavior.
- Add Core regression tests and documentation.
- Coordinate Edge PR for application discriminator and ACK metadata clearing.
- Use #248 for full real Edge/Core staging scenarios and accepted evidence.

## Out of scope

- New control, actuator, GPIO, or physical-action behavior.
- Automatic reactivation of a decommissioned device.
- Deleting or rewriting production history.
- A write HTTP API for lifecycle changes.
- Reimplementing #248/#250’s complete cross-repository harness in this issue.
- Weakening Core’s fail-safe interpretation of ambiguous legacy Edge health.
- Adding TUI features or unrelated API version endpoints.

## Architecture placement

- Storage lifecycle state belongs to the Core storage/model and migration layer.
- Lifecycle aggregation belongs to read-model consumers and State Estimator device selection.
- Worker health remains an operational signal owned by the worker and consumed read-only by API.
- ACK correctness remains owned by the Edge spool/delivery layer; Core keeps the existing `record_id` contract.
- No change crosses the Guardrails, Executor, actuator, or real-hardware boundary.

## Affected contracts and consumers

- Storage: new additive lifecycle columns and append-only lifecycle events; UTC timestamps; bounded enum/reason values.
- API: existing device-specific reads remain compatible; `/api/v1/devices` may expose lifecycle fields additively. `senior-pomidor.operator.v1` shape remains unchanged; aggregate contents become active-fleet scoped.
- Compose: new shared health volume is project-scoped and isolated between dev/staging/production projects.
- Edge/Core: `service_manager=none` is required for canonical Docker application health; legacy ambiguous payloads remain `UNKNOWN` until the Edge update.
- ACK: accepted/duplicate responses with the same `record_id` remain delivered and idempotent; mismatch remains retry/error.
- State Estimator: decommissioned devices are not processed in normal cycles; historical reads remain available.
- Dashboards/export: active-fleet queries filter lifecycle state; no new public private fields.
- Fixtures/reports/docs: add v0.2.5-shaped database fixture, lifecycle fixtures, multi-container health evidence and compatibility report references.

## Safety/risk classification

- Task classes from `TEST_MATRIX.md`: `pure_software`, `schema_data_contract`, `infrastructure_deployment`, `edge_hardware_integration` for coordinated Edge validation.
- Risk flags: `data_loss_migration`, `edge_server_compatibility`, `production_availability`, `public_contract`.
- Applicable failures: `SP-FAIL-001` (exact Compose/image render), `SP-FAIL-002` (worker health), `SP-FAIL-003` and `SP-FAIL-004` (isolated staging/release artifact), `SP-FAIL-005` (restore readiness), `SP-FAIL-014` (Windows/Linux paths), `SP-FAIL-015` (packaging/build).
- Production writes, migration execution, Edge canary, physical hardware and rollback evidence belong to the authorized release owner. Coding and CI use isolated environments and synthetic data.

## Proposed implementation sequence

1. Obtain human approval for this brief and create/link the Edge ACK issue/PR.
2. Add the lifecycle migration with existing rows defaulted to `ACTIVE`; add constraints, indexes and append-only events.
3. Implement a data-preserving downgrade: retain additive lifecycle objects while moving Alembic revision to `0009`; make re-upgrade validate/reuse them. This keeps v0.3.0 readiness valid after rollback.
4. Implement the admin CLI with `show` and guarded `set`, mandatory `--apply`, expected-state check, idempotent target repeat, bounded reason code and one transaction for state/event.
5. Keep incoming telemetry for decommissioned devices without changing lifecycle state.
6. Apply lifecycle filtering to State Estimator and all global operator/anomaly/active-fleet consumers; retain device-specific history.
7. Add the named worker-health volume to base and staging Compose; set API read-only and worker read-write; use one path and atomic file replacement.
8. Add focused unit, migration, Compose and regression tests before changing release documentation.
9. Merge the coordinated Edge fix: emit `service_manager=none` in Docker and clear aggregate ACK error metadata after accepted/duplicate delivery while preserving attempt history.
10. Run #248 real cross-repository scenarios against the exact Core/Edge pair, create accepted evidence, then perform exact-bundle rehearsal, canary and observation under the production runbook.

## Failure modes

| Failure | Detection | Safe behavior | Test/recovery |
| --- | --- | --- | --- |
| Health volume absent | API reports missing file | `UNKNOWN`, no false healthy result | Rendered Compose and multi-container test; fix mount before promotion |
| Health file partial/malformed | JSON parse/read failure | `UNKNOWN` | Atomic-write and malformed-file tests |
| Health file stale | age exceeds 90 seconds | `WARN` | Clock/stale fixture test; recover worker |
| Lifecycle state mismatch | CLI expected state differs | Non-zero exit, no write | Concurrent/incorrect transition tests |
| Decommissioned node sends data | ingest event accepted | Store data, do not reactivate | Ingress regression test |
| Legacy Edge health is ambiguous | missing discriminator | `UNKNOWN`, no fail-open | Legacy fixture test; deploy compatible Edge |
| ACK record ID mismatch | returned ID differs | retry, keep error history | Lost/mismatched ACK test |
| Later ACK succeeds | accepted/duplicate same ID | mark delivered and clear current aggregate error | Edge spool regression test |
| Migration rollback | DB at additive schema with v0.3.0 | old app remains ready; lifecycle metadata retained | upgrade/downgrade/re-upgrade test |
| Qualification scenario not executed | `NOT_RUN` report | release validation fails | #248 evidence and validator `--require-pass` |

## Backward compatibility

- Existing telemetry v1/v2 and record-id behavior remain unchanged.
- Existing devices are `ACTIVE` after migration; no implicit production decommission is performed by migration.
- Decommission is explicit and reversible only through guarded admin CLI.
- Decommissioned ingress is persisted but never auto-reactivates the device.
- v0.3.0 ignores extra lifecycle schema objects and remains compatible with the additive database shape.
- Rollout order: Core compatible build → migration/rehearsal → Edge compatible build → canary → observation.
- Rollback changes only application image/configuration and preserves PostgreSQL data, health metadata and evidence; additive lifecycle schema is retained.

## Testing plan

Required automated checks:

```text
python -m pytest tests/test_health_summary.py tests/test_operator_summary.py tests/test_operator_edge_reliability.py tests/test_mqtt_worker.py -q
python -m pytest tests/test_telemetry_migration.py tests/test_api.py tests/test_docker_e2e.py -q
python -m pytest -q
nox -s lint format_check types
```

Required additional coverage:

- Alembic upgrade from `0009`, backfill, guarded lifecycle transitions, data-preserving downgrade and re-upgrade.
- Real API/worker containers sharing health volume with restart and malformed/stale cases.
- Historical active/inactive device fixture through State Estimator, operator, anomaly, dashboard and exporter consumers.
- Edge accepted, duplicate, lost ACK, mismatched ACK, replay and restart cases.
- Rendered dev/staging/prod Compose with immutable images and isolated volumes/ports.
- #248 cross-repository staging report: all required implemented scenarios `PASS`; no mandatory `NOT_RUN`.
- Exact release bundle rehearsal and rollback are manual; physical and production outcomes remain manual evidence.

## Observability

- API `/health/summary` exposes worker, telemetry and Edge reliability status with bounded reason codes.
- Operator views expose active-fleet status; device-specific endpoints remain the audit path for decommissioned history.
- Lifecycle CLI emits bounded transition result and reason code; lifecycle event rows provide durable audit.
- Edge spool keeps delivery-attempt history; aggregate current error fields are cleared only after matching accepted/duplicate ACK.
- Reports contain UTC timestamps, exact artifact identities and sanitized evidence only; no credentials, raw payloads, hostnames or private paths.

## Documentation updates

- Update `docs/CONTRACTS.md`, `docs/OPERATIONS.md`, `docs/POST_MERGE_PREPRODUCTION_QUALIFICATION.md` and `docs/PRODUCTION_RELEASE_INSTALLATION_RUNBOOK.md`.
- Document lifecycle CLI, decommissioned ingress semantics, shared health volume, exact API-port discovery and rollback compatibility.
- Add migration/schema examples and link the accepted #248 report.
- Update `CHANGELOG.md`, `.ai/CURRENT_STATE.md` and release evidence only after the immutable v0.3.1 identities exist.

## Rollout and rollback

- Preconditions: approved brief, Core/Edge immutable pair, migration backup/restore evidence, rendered Compose, #248 accepted report and release owner approval.
- Rehearsal uses isolated project, paths, credentials, network and external export disabled.
- Production rollout is Core-first; do not update Edge until Core health and compatibility gates pass.
- Abort on readiness failure, unexplained `UNKNOWN/ALERT`, stale active Edge, ACK mismatch, backlog growth, data/count mismatch or port/path collision.
- Rollback uses the approved application-only procedure. Do not drop volumes, delete lifecycle/history rows or downgrade destructive schema objects.
- Post-rollback: verify old image identity, `/ready`, `/health`, ingestion, historical reads and preserved migration/data counts.

## Acceptance criteria

- [ ] Shared health path works in real separate API/worker containers; API read-only, worker writable.
- [ ] Active Edge health summary is `OK/FRESH`; missing, malformed, stale and stopped health fail safe.
- [ ] Lifecycle migration, admin CLI, audit events and guarded reversible transitions are tested.
- [ ] Decommissioned devices remain readable and do not affect active-fleet aggregates or State Estimator cycles.
- [ ] Decommissioned ingress is retained without automatic reactivation.
- [ ] Edge emits canonical Docker application discriminator and Core evaluates it as `OK` when process is healthy.
- [ ] ACK mismatch remains retry/error; later matching accepted/duplicate delivery clears current aggregate error without deleting history.
- [ ] v0.3.0 rollback remains ready after the additive migration and lifecycle data is retained.
- [ ] Full automated matrix passes; #248 real staging evidence is accepted; exact-bundle rehearsal, canary and observation pass.
- [ ] Contracts, operations, qualification, rollback and release evidence documentation is updated.

## Blocking open questions

None. Human approval of this brief and Edge PR coordination are required before coding; they are workflow gates, not implementation choices.

## Evidence and references

- Issue: `https://github.com/cracketus/senior-pomidor-server/issues/357`
- Related server issues: #248, #250.
- Related Edge epic: `https://github.com/cracketus/senior-pomidor-plant-v2/issues/97`.
- Core revision/image observed above; future v0.3.1 identities are Unknown until release.
- Production observations supplied by operator on `2026-09-13`; private addresses and credentials intentionally omitted.
- Applicable context: `.ai/CORE_INVARIANTS.md`, `.ai/ARCHITECTURE_RULES.md`, `.ai/TEST_MATRIX.md`, `.ai/KNOWN_FAILURES.md`.

Approval of this brief does not itself authorize production deployment, production data/secrets access, or real hardware activation.
