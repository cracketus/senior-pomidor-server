# Implementation Report: v0.3.1 Core lifecycle and health reliability

Issue/brief: #357 / `.ai/planning/implementation-brief-357.md`

Agent run ID / audit artifact: `agent-run-357-20260913-core` / this report

Branch/worktree: current user worktree; pre-existing dirty docs and release assets preserved

Task classes and risk flags: `pure_software`, `schema_data_contract`, `infrastructure_deployment`;
`data_loss_migration`, `edge_server_compatibility`, `production_availability`, `public_contract`

Applicable `SP-FAIL-*` IDs: `SP-FAIL-001`, `SP-FAIL-002`, `SP-FAIL-003`, `SP-FAIL-004`,
`SP-FAIL-005`, `SP-FAIL-014`, `SP-FAIL-015`

## Implemented behavior

- Added additive `ACTIVE`/`DECOMMISSIONED` device state and append-only UTC lifecycle events.
- Added guarded, idempotent `show`/`set` lifecycle CLI; writes require `--apply`, validate expected state
  and bounded reason code, and commit state plus audit event in one transaction.
- Preserved decommissioned-device telemetry ingress without automatic reactivation.
- Excluded decommissioned devices from estimator cycles, operator aggregates, active anomaly summaries,
  Grafana export and aggregate latest-device telemetry; device-specific reads remain unchanged.
- Added atomic worker health-file replacement and project-scoped Compose volume with API `ro` and worker `rw`.

## Files changed and purpose

- `app/models.py`, `migrations/versions/0010_device_lifecycle.py`: additive schema and data-preserving downgrade.
- `app/device_lifecycle.py`, `tools/lifecycle.py`: lifecycle domain operations and human CLI.
- `app/operator_summary.py`, `app/state_estimator_worker.py`, `app/state_estimator/persistence.py`,
  `app/grafana_cloud_exporter.py`, `app/api.py`: active-fleet consumer filtering and additive API fields.
- `app/worker_health.py`, `docker-compose.yml`: atomic health publication and shared volume.
- `tests/test_device_lifecycle.py`: lifecycle and ingress regression coverage.
- `docs/CONTRACTS.md`, `docs/OPERATIONS.md`, qualification/release runbooks: operational contract and gates.

## Design decisions

- Lifecycle is additive and string-backed to keep v0.3.0 readers compatible with the database shape.
- Migration downgrade is intentionally a no-op for lifecycle objects, retaining data and allowing safe
  re-upgrade validation/reuse.
- Incoming writes update freshness fields but never lifecycle state; only the guarded admin operation changes it.
- Health replacement uses a same-directory flushed temporary file and `os.replace`, preserving fail-safe
  missing/malformed/stale semantics.

## Deviations from brief

- Edge `service_manager=none` and ACK aggregate-metadata fixes are not in this repository and were not changed.
- Real separate-container, #248 staging, exact-bundle, canary, rollback, hardware and production evidence remain
  `NOT_RUN` and require the coordinated Edge/release owner.

## Tests added

- `tests/test_device_lifecycle.py`: mandatory apply, expected-state guard, idempotent repeat, audit event,
  decommissioned ingress retention and no reactivation.

## Commands run and results

| Status | Command | Result/evidence |
| --- | --- | --- |
| PASS | `python -m pytest tests/test_device_lifecycle.py tests/test_lifecycle.py tests/test_health_summary.py tests/test_operator_summary.py tests/test_mqtt_worker.py tests/test_compose_config.py tests/test_telemetry_migration.py -q` | 60 passed |
| PASS | `nox -s lint format_check types` | lint, format and mypy passed |
| PASS | `git diff --check` | no whitespace errors |
| FAIL | `python -m pytest -p no:cacheprovider -q` | 658 passed, 12 skipped; existing `tests/test_release_assets.py::test_production_installation_requires_verified_rollback_bundle` fails because pre-existing modified runbook lacks its expected placeholder |
| NOT_RUN | Compose multi-container/restart/malformed health rehearsal | requires isolated Docker execution and release workflow |
| NOT_RUN | #248 Edge/Core scenarios, Edge ACK/discriminator, canary, production and physical checks | coordinated external/manual evidence; not authorized here |

## Compatibility checks

Existing telemetry v1/v2 and record IDs remain unchanged. Existing devices backfill as `ACTIVE`.
Device-specific API history paths were not lifecycle-filtered. SQLite migration upgrade was exercised
against populated pre-0009 data; PostgreSQL upgrade/restore evidence remains release-owner work.

## Safety impact

No production writes, secrets, GPIO, actuator, Guardrails/Executor, or external export were used.
The change preserves historical rows and uses an additive, non-destructive rollback. Compose changes are
configuration-only and must be rendered through the isolated task workflow before startup.

## Known limitations

The coordinated Edge implementation and real cross-repository qualification are pending. A full pytest
release-assets failure remains attributable to pre-existing user edits in the release runbook and must be
resolved by the documentation/release owner.

## Documentation changes

Contracts, operations, pre-production qualification and production rollback gates document lifecycle CLI,
decommissioned ingress, shared health volume and the remaining Edge/#248 evidence boundary.

## Manual verification steps

Release owner must render base/staging/production Compose, verify volume permissions and separate API/worker
containers, run upgrade/rollback/restore rehearsal with counts and hashes, then execute accepted #248 scenarios.
Current status: `NOT_RUN`.

## Final diff review

No secrets, debug artifacts, destructive commands or physical paths were added. Pre-existing modified
documentation and untracked release assets were preserved and not incorporated into implementation logic.

## Review-fix follow-up

Reviewer findings P1/P2 were fixed: the Compose health volume now uses the active project-derived
name, and both ORM metadata and migration enforce `ACTIVE`/`DECOMMISSIONED` with a database CHECK
constraint. An explicit invalid-state regression test was added. The repository has no callable
`$review-agent` in this environment; local re-review and focused checks passed.

The updated production and pre-production runbooks remain included. Their release-specific rollback
identity is now validated by `tests/test_release_assets.py` as a real lowercase SHA rather than an
obsolete placeholder.
