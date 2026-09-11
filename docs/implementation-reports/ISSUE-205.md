# Implementation Report: versioned operator summary/read-model API

Issue/brief: `.ai/planning/implementation-brief-205.md` (#205)

Agent run ID / audit artifact: `20260911-issue-205-coder` / `.ai/agent-runs/20260911-issue-205-coder.json`

Branch/worktree: current user worktree; unrelated `.ai/planning/implementation-brief-336.md` preserved.

Task classes and risk flags: `pure_software`, `schema_data_contract`; `edge_server_compatibility`, `public_contract`.

Applicable `SP-FAIL-*` IDs: `SP-FAIL-009`, `SP-FAIL-010`, `SP-FAIL-011`, `SP-FAIL-014`, `SP-FAIL-015`.

## Implemented behavior

- Added strict, versioned status, plants, edges, anomalies, photos, and decisions responses.
- Added deterministic persisted-row aggregation with bounded collections and explicit partial results.
- Reused the existing edge reliability builder and projected state/pod data through allowlists.
- Kept host health and decisions explicitly unavailable/not implemented; no estimator or ActionSimulation read is used.
- Added OpenAPI response models, Draft 2020-12 schema, contract documentation, current-state, and changelog updates.
- Review follow-up: `/status` now reports `PARTIAL` when its bounded aggregate truncates nodes/edges,
  freshness is aggregated across state, plant, and edge observations, and the published schema validates
  per-view data shapes with strict nested objects.
- Additional review follow-up: stale state escalates aggregate status, collection views expose computed
  freshness, and active/high-severity anomalies participate in the operator status.
- Latest review follow-up: status selects the globally newest persisted state, active-anomaly precedence is
  computed database-side with bounded memory, and known devices without telemetry are represented as unknown edges.

## Files changed and purpose

- `app/operator_summary.py`: strict models, allowlist projection, deterministic read service.
- `app/api.py`: six additive routes and bounded storage error mapping.
- `tests/test_operator_summary.py`: real FastAPI/SQLite empty-storage route and decisions contract checks.
- `docs/schemas/operator-v1.schema.json`: versioned contract schema.
- `docs/CONTRACTS.md`, `.ai/CURRENT_STATE.md`, `CHANGELOG.md`: contract and operational documentation.

## Deviations from brief

- None known. Real PostgreSQL/Docker replay and real Edge canary remain manual evidence.

## Commands run and results

| Status | Command | Result/evidence |
| --- | --- | --- |
| PASS | `python -m pytest -q tests/test_operator_summary.py tests/test_operator_edge_reliability.py tests/test_api.py -p no:cacheprovider` | 99 passed. |
| PASS | `ruff check app/operator_summary.py app/api.py` | Passed. |
| PASS | `python -m mypy app/operator_summary.py app/api.py` | Passed after final typing fix. |
| PASS | `git diff --check` | No whitespace errors. |
| PASS | `python -m pytest -q -p no:cacheprovider` | 629 passed, 12 skipped. |
| PASS | `python -m pytest -q tests/test_edge_integration_fixtures.py tests/test_contract_fixtures.py tests/test_operator_summary.py tests/test_operator_edge_reliability.py tests/test_api.py -p no:cacheprovider` | 120 local fixture/HTTP/operator contract tests passed. |
| PASS | `nox -s lint format_check types` | Lint and types passed; format check passed on rerun after mechanical formatting. |
| PASS | Draft 2020-12 schema validation and Pydantic round-trip | All six operator views validate against the published schema; edge fixture and Pydantic round-trip pass. |
| PASS | Review regression checks | Full suite, multi-node newest-state, bounded anomaly precedence, unknown-edge, and strict schema checks pass. |
| FAIL | `python -m tools.validate_change --base origin/main --task-key tomato-205-operator-read-model --explain --force full` | Tool reported `unknown agent task`; no task record exists in this checkout. |
| NOT RUN | PostgreSQL/Docker replay and Edge canary | Requires isolated operator-owned environment/evidence. |

## Safety impact

Read-only additive API. No migration, production access, secret access, export, hardware, Guardrails,
Executor, or physical-action path changed. Rollback is reverting the additive code/schema/docs.

## Known limitations

Host health, Control decisions, and physical Edge behavior remain not implemented or manual by design.

## Manual verification steps

`NOT RUN`: isolated loopback read against synthetic PostgreSQL data; verify counts before/after are unchanged.
Real Edge/Core canary and production verification remain `NOT RUN`.

## Final diff review

Unrelated #336 planning file preserved. No migrations, raw payload projection, estimator invocation, debug
output, credentials, or destructive commands added.
