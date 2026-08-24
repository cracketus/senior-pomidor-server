# Implementation Report: versioned operator edge reliability API

Issue/brief: Human-approved implementation plan for server issue #228.

Agent run ID / audit artifact: `20260824-issue-228-coder` /
`.ai/agent-runs/20260824-issue-228-coder.json`.

Branch/worktree: `feature/TOMATO-228-edge-reliability-read-api` /
`.agent-worktrees/tomato-228-edge-reliability-read-api`.

Task classes and risk flags: `pure_software`, `schema_data_contract`,
`edge_hardware_integration`; `edge_server_compatibility`, `public_contract`.

Applicable `SP-FAIL-*` IDs: `SP-FAIL-009`, `SP-FAIL-010`, `SP-FAIL-011`,
`SP-FAIL-014`, `SP-FAIL-015`.

## Implemented behavior

- Added `GET /api/v1/operator/edges/{device_id}/reliability` with typed
  `senior-pomidor.operator.edge-reliability.v1` output.
- Deterministically selects the latest telemetry by `timestamp_utc DESC, id DESC` without loading pod
  readings/errors or accessing raw payload data.
- Uses the #227 evaluator as the sole source of current status/reason mappings and projects only bounded
  watchdog, spool, and application fields.
- Applies the 1200-second freshness boundary: fresh evaluates normally, stale exposes safe last-observed
  values with only `UNKNOWN` statuses, and future/invalid timestamps hide reliability details.
- Returns bounded `400`, `404`, and `503` errors and preserves the existing private/LAN API policy.

## Files changed and purpose

- `app/operator_edge_reliability.py`: strict response models and pure read-model builder.
- `app/api.py`: validation, deterministic latest query, bounded errors, and typed route.
- `docs/schemas/operator-edge-reliability-v1.schema.json`: standalone Draft 2020-12 contract.
- `tests/fixtures/contracts/operator_edge_reliability_v1.json`: sanitized synthetic contract example.
- `tests/test_operator_edge_reliability.py`, `tests/test_contract_fixtures.py`: builder, endpoint,
  OpenAPI, schema, round-trip, privacy, and compatibility evidence.
- `docs/CONTRACTS.md`, `.ai/CURRENT_STATE.md`, `CHANGELOG.md`: consumers, rollout boundary, current state,
  and release notes.
- `.ai/agent-runs/20260824-issue-228-coder.json`: bounded audit record.

## Design decisions

- Kept freshness policy in the read model while delegating every reliability state/status/reason mapping
  to the existing evaluator.
- Made nullable response fields required in Pydantic and JSON Schema so JSON keys remain stable for CLI
  consumers and legacy telemetry.
- Preserved last-observed allowlisted values only for stale telemetry; future/invalid observation time
  projects no subsystem details because freshness cannot be trusted.
- Used one focused query with no ORM relationship loader options; no schema or database migration is needed.

## Deviations from brief

- The isolated-task wrapper accepts only `TOMATO-228` issue identifiers and therefore generated task key
  `tomato-228-edge-reliability-read-api`, rather than the brief's unsupported
  `issue-228-edge-reliability-read-api`. No behavior or scope deviation.

## Tests added

- Healthy, recovery/restart, suppression, backlog/degraded spool, stopped application, missing/partial
  legacy blocks, simultaneous findings, and evaluator ordering.
- Freshness at 0, 1200, 1200.001 seconds and future/invalid timestamps, including stale last-observed data.
- HTTP success, unsafe device ID, missing telemetry, bounded database failure, deterministic query order,
  absence of eager loading, and OpenAPI response-model identity.
- Draft 2020-12 fixture validation, Pydantic round trip, nullable-key stability, percent bounds, and privacy
  exclusion of raw payload, reason/details, IDs, service names, and paths.

## Commands run and results

| Status | Command | Result/evidence |
| --- | --- | --- |
| PASS | `python -m pytest tests/test_operator_edge_reliability.py tests/test_api.py tests/test_edge_reliability.py tests/test_health_summary.py tests/test_contract_fixtures.py tests/test_public_status.py tests/test_grafana_cloud_exporter.py -q` | 137 passed before the final edge-fixture assertion; the post-change `-p no:cacheprovider` rerun passed 138 tests. |
| PASS | `python -m pytest -q` | 430 passed, 3 skipped before the final edge-fixture assertion; the post-change `-p no:cacheprovider` rerun passed 431 tests, 3 skipped. |
| PASS | `nox -s lint format_check types` | Ruff lint/format and mypy passed after formatting the new files. |
| PASS | `git diff --check` | No whitespace errors; Git emitted only line-ending normalization warnings. |
| FAIL | `python -m tools.validate_change --base origin/main --task-key tomato-228-edge-reliability-read-api --explain --force full` | Focused 30, full 431/3 skipped, quality, and diff checks PASS; overall exit 1 because the maturity gate reports the present audit/brief/evidence references missing. |
| NOT RUN | Manual private edge/API canary | Requires operator-observed server candidate and real edge telemetry. |

After the final fixture assertion, an exact focused pytest run completed all 30 selected tests but failed
during session teardown because Windows denied `.pytest_cache` access (`SP-FAIL-014`). Cache-disabled
focused/full reruns and the canonical validator's isolated `--basetemp` runs passed; no cache deletion or
permission mutation was performed.

## Compatibility checks

- Existing latest/history, health summary, contract fixtures, public status, and Grafana Cloud exporter
  tests pass without response-shape additions.
- Current and legacy reliability blocks round-trip through bounded ingestion/evaluator/read paths; the new
  contract is additive and has named future consumers #205 and #206.
- Server-only rollout requires no edge or database change. The real `pomidorctl` consumer remains owned by
  #206 and is not present in this repository.

## Safety impact

- Read-only projection only. No production access/write, deployment, recovery action, GPIO/actuator path,
  Guardrails/Executor change, Compose mutation, external export, secret access, or migration.
- Rollback is the previous application image; stored telemetry JSONB remains compatible and needs no cleanup.

## Known limitations

- A deployed private edge/API canary remains manual. CI cannot prove real watchdog, spool, systemd, radio,
  storage, or physical-world behavior.
- Canonical validation remains overall `FAIL` because its maturity gate does not load the task's present
  versioned audit, human-approved brief, or test evidence references. All selected executable checks pass;
  a maintainer must resolve or waive this tooling defect.
- Reliability history, operator aggregation/list, CLI/auth configuration, and metrics remain owned by
  #229/#205/#206 and outside this implementation.

## Documentation changes

- `docs/CONTRACTS.md` defines the endpoint, schema, nullable and freshness semantics, privacy boundary,
  consumers, and HTTP behavior.
- `.ai/CURRENT_STATE.md` and `CHANGELOG.md` record the deployable contract and release behavior.
- The JSON Schema and synthetic fixture are the machine-readable contract/example pair.

## Manual verification steps

- `NOT RUN`: on a deployed server candidate, query healthy, recovering, suppressed, stale, and legacy
  devices through the private endpoint. Abort if stale becomes WARN/ALERT, suppression appears OK, missing
  blocks appear healthy, excluded fields leak, or existing API/public/export shapes change.

## Final diff review

- Unrelated changes were absent. The diff was reviewed for duplicate severity mappings, unsafe freshness,
  missing nullable keys, schema/OpenAPI drift, eager relationship loading, private-field leakage, public
  export changes, secrets, debug artifacts, database changes, and rollback gaps.
