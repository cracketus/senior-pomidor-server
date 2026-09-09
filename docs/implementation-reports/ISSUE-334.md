# Implementation Report: #334 — Pure target capability and interval evaluation

Issue/brief: `#334`, `.ai/planning/implementation-brief-334.md`
Agent run ID / audit artifact: `20260909-issue-334-coder` / `.ai/agent-runs/20260909-issue-334-coder.json`
Branch: `feature/TOMATO-334-map-capability-evaluator`

## Implemented behavior

Added frozen `senior-pomidor.map.v1` capability contracts and a pure evaluator. It validates the
topology/evidence/request snapshot, evaluates explicit target expressions independently, applies
`ALL_OF`/`ANY_OF` precedence, emits bounded opaque evidence references, and sweeps deterministic UTC
half-open intervals. Freshness is inclusive through `max_age + 1 microsecond`; AS_KNOWN_CORE uses
receipt eligibility and RECONSTRUCTED uses the cutoff. No API, startup, database, estimator, control,
export, or hardware wiring was added.

## Files changed

- `app/map/capability.py` — immutable result models, enums, opaque references, canonical digest.
- `app/map/evaluator.py` — fail-closed pure validation, leaf evaluation, reducers, and interval sweep.
- `app/map/__init__.py` — additive exports.
- `tests/test_map_evaluator.py` — threshold, missing-history/binding, digest/mismatch, delayed receipt, latest invalidation, reducers, and contradiction tests.
- `docs/TOMATO_BRAIN_MAP_R1_SPEC.md`, `.ai/CURRENT_STATE.md` — status updates.

## Evidence

| Status | Check | Result |
| --- | --- | --- |
| PASS | `python -m pytest -q tests/test_map_evaluator.py tests/test_map_reader.py tests/test_map_topology.py tests/test_temporal_integrity.py tests/test_edge_integration_fixtures.py -p no:cacheprovider` | 87 passed |
| PASS | `python -m pytest -q -p no:cacheprovider` | 591 passed, 12 skipped |
| FAIL | `nox -s lint format_check types` | lint/types passed; format session was interrupted after a repeated editable-install hang; local `ruff format --check` passed |
| PASS | `git diff --check` | clean; only line-ending warnings |
| FAIL | `python -m tools.validate_change --base origin/main --task-key tomato-334-map-capability-evaluator --explain --force full` | Tool reports unknown agent task key; no registered task entry exists |
| PASS | `python -m tools.agent_audit .ai/agent-runs/20260909-issue-334-coder.json` | bounded artifact accepted |
| NOT_RUN | independent review | Required before merge |

## Safety, compatibility, and rollback

The change is additive and inactive. Existing topology, reader, telemetry, estimator, API, public
contracts, database state, external export, and physical paths are unchanged. Rollback is removal of
the additive commit; no migration or data restore is required. Production, staging, real calibration,
hardware, and operator UI evidence are `NOT_RUN`.

## Known limitations

The evaluator has no runtime route, concurrency gate, pagination, or real-data activation; those remain
scoped to later briefs. Independent review remains open.
