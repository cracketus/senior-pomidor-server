# Implementation Report: edge reliability telemetry normalization

Issue/brief: Human-approved implementation brief for server issue #226.

Agent run ID / audit artifact: `20260824-issue-226-coder` /
`.ai/agent-runs/20260824-issue-226-coder.json`.

Branch/worktree: `feature/ISSUE-226-reliability-telemetry` /
`.agent-worktrees/issue-226-reliability-telemetry`.

Task classes and risk flags: `pure_software`, `schema_data_contract`,
`edge_hardware_integration`; `edge_server_compatibility`, `public_contract`.

Applicable `SP-FAIL-*` IDs: `SP-FAIL-009`, `SP-FAIL-010`, `SP-FAIL-011`,
`SP-FAIL-014`. `SP-FAIL-015` is not applicable because no top-level package was added.

## Implemented behavior

- Persists allowlisted `system_health.watchdog`, `spool`, and `application` fields in the existing
  JSONB value through shared HTTP/MQTT persistence.
- Preserves missing versus empty object blocks and explicit null for documented nullable fields.
- Drops malformed optional fields independently, rejects booleans as integers, enforces non-negative
  counts/bytes/durations, bounds disk usage to `0..100`, validates UTC `Z` timestamps, and bounds
  state/code/identifier strings to 256 characters without changing case.
- Excludes error details, nested application errors, and unknown fields. Raw payload storage,
  `record_id` idempotency, alert/summary semantics, public status, and Grafana export remain unchanged.

## Files changed and purpose

- `app/telemetry.py`: typed tolerant allowlist normalization.
- `docs/schemas/telemetry-v2.schema.json`: strict producer definitions with forward-compatible objects.
- `docs/CONTRACTS.md`: producer/server-reader semantics, privacy, and consumer scope.
- `tests/fixtures/contracts/telemetry_v2.json`: server reliability contract fixture.
- `tests/fixtures/edge_integration/telemetry_reliability.json`: synthetic private-safe copied edge fixture
  with schema/runtime/revision provenance.
- `tests/test_api.py`: normalization and HTTP persistence failure-path coverage.
- `tests/test_contract_fixtures.py`: Draft 2020-12 validation and serialization round trips.
- `tests/test_edge_integration_fixtures.py`: full HTTP/MQTT persistence, reads, and replay coverage.
- `tests/test_public_status.py`, `tests/test_grafana_cloud_exporter.py`: privacy regressions.
- `.ai/agent-runs/20260824-issue-226-coder.json`: bounded sanitized audit record.

## Design decisions

- Used per-field tolerant normalization only for the three additive reliability blocks. Existing strict
  validation for older health blocks remains intact.
- Included every field returned by the pinned edge spool health runtime except `last_error_detail` and
  `worker_last_error`; `aggregate` and `indicator` remain outside scope.
- Kept `additionalProperties: true` in producer schema objects for forward compatibility while known
  properties remain strictly typed.

## Deviations from brief

- None in implementation. A live edge/PostgreSQL canary is manual and remains `NOT_RUN`.

## Tests added

- Full, partial, empty, missing, nullable, malformed, out-of-range, unknown, and privacy cases for all
  three blocks.
- Draft 2020-12 producer validation and server/copied-edge serialization round trips.
- HTTP/MQTT fixture replay through persistence and latest/history reads, including cross-transport
  duplicate `record_id` behavior.
- Public status and Grafana Cloud allowlist regressions.

## Commands run and results

| Status | Command | Result/evidence |
| --- | --- | --- |
| PASS | `python -m pytest tests/test_api.py tests/test_mqtt_worker.py tests/test_contract_fixtures.py tests/test_edge_integration_fixtures.py tests/test_public_status.py tests/test_grafana_cloud_exporter.py -q` | 92 passed. |
| PASS | `python -m pytest -q` | 371 passed, 3 skipped. |
| PASS | `nox -s lint format_check types` | Ruff lint/format and mypy passed. |
| PASS | `git diff --check` | No whitespace errors. |
| PASS | `python -m tools.agent_audit .ai/agent-runs/20260824-issue-226-coder.json` | Audit artifact valid. |

The task-local `.pytest_cache` was removed before final pytest invocations because repeated reuse hit a
Windows ACL/cache-provider error after otherwise successful tests. Exact pytest commands then exited 0.

## Compatibility checks

- Legacy telemetry v1/v2 fixtures remain covered by the full suite.
- The copied edge fixture is pinned to edge revision `e1244ae0f9e4f08e5b272839c970e13f4fb7dcc9` and
  does not access a sibling checkout during tests.
- HTTP and MQTT share the same persistence normalizer; replay retains one record and duplicate ACK.
- Named read consumers return the blocks only under private `system_health`; public status and Grafana
  Cloud projections exclude them.

## Safety impact

- No production access, deployment, Compose mutation, secrets, external export, GPIO, actuator, database
  migration, or destructive data operation occurred.
- Change is additive and reversible by restoring the previous application image. Existing JSONB stays
  valid and requires no cleanup.

## Known limitations

- The automated transport tests use the repository's isolated SQLAlchemy test database; a live
  PostgreSQL and real-edge canary remain manual rollout evidence.
- Health semantics for the new diagnostics are deferred to #227.

## Documentation changes

- `docs/CONTRACTS.md` documents producer types, tolerant server behavior, null semantics, bounded strings,
  private-field exclusions, and unchanged consumers.
- `docs/schemas/telemetry-v2.schema.json` is the machine-readable producer contract.

## Manual verification steps

- `NOT_RUN`: after server rollout, use one supervised edge canary to verify HTTP ACK, MQTT mirror,
  persisted PostgreSQL JSONB, latest/history reads, and absence from public/export projections. Abort on
  ingestion rejection, duplicate row, transport mismatch, legacy regression, or public leakage.

## Final diff review

- Unrelated changes were absent. The diff was checked for secrets, private fixture data, debug artifacts,
  weakened validation, contract drift, public leakage, and rollback gaps.
