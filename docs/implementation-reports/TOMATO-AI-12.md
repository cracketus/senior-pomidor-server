# Implementation Report: Health summary pilot

Issue/brief: [#132](https://github.com/cracketus/senior-pomidor-server/issues/132) /
[approved brief](../../.ai/implementation-briefs/TOMATO-AI-12-health-summary.md)

Branch/worktree: `main` / current checkout. Isolated task creation was attempted but could not
create `.git/index.lock` because the managed checkout denied Git index writes; no branch or
worktree was created.

Task classes and risk flags: `pure_software`, `schema_data_contract` / no risk flags.

Applicable `SP-FAIL-*` IDs: `SP-FAIL-009`, `SP-FAIL-011`, `SP-FAIL-014`.

## Implemented behavior

- Added read-only `GET /health/summary` with optional `node_id`.
- Added versioned `health_summary_v1` output with bounded components, reasons, UTC generation time,
  and freshness thresholds.
- Composed existing readiness, worker-health, telemetry, and sensor-health signals only.
- Missing, malformed, stale, critical, and unavailable inputs produce non-healthy statuses and safe
  reason codes; no recovery or mutation is triggered.
- Preserved existing `/health`, `/ready`, telemetry, MQTT, storage, estimator, control, and
  actuator behavior.

## Files changed and purpose

- `app/health_summary.py`: deterministic health-summary composition and failure handling.
- `app/main.py`: new read-only HTTP route and dependency wiring.
- `docs/schemas/health-summary-v1.schema.json`: versioned response schema.
- `tests/fixtures/contracts/health_summary_v1.json`: synthetic contract fixture.
- `tests/test_health_summary.py`: route and stale/missing failure-path coverage.
- `tests/test_contract_fixtures.py`: contract fixture/version regression coverage.
- `docs/CONTRACTS.md`: endpoint, schema, freshness, and safety semantics.
- `docs/OPERATIONS.md`: operational interpretation and non-remediation guidance.
- `.ai/implementation-briefs/TOMATO-AI-12-health-summary.md`: approved brief.

## Design decisions

- `GET /health/summary` is additive and internal-only; existing health/readiness contracts remain
  unchanged.
- `node_id` is optional. Without it, telemetry and sensor-health are explicitly server-scoped and
  do not claim node health. With it, absent or stale node evidence is non-healthy.
- Worker freshness is 90 seconds and telemetry/sensor freshness is 1200 seconds, matching the
  approved pilot brief. Thresholds are summary semantics only and do not alter existing alerts.
- The summary reads existing files/database rows and caps reasons at 20; raw payloads, paths,
  network details, and secrets are not returned.

## Deviations from brief

- Coding used the current `main` checkout because the isolated task wrapper could not create a Git
  index lock under the managed filesystem permission profile. This is recorded for human review;
  no production or external state was accessed.

## Tests added

- Current server summary with bounded output.
- Missing worker health.
- Missing node telemetry and sensor health.
- Stale telemetry and sensor health.
- Versioned health-summary contract fixture and schema inventory.

## Commands run and results

| Status | Command | Result/evidence |
| --- | --- | --- |
| PASS | `python -m pytest tests/test_health_summary.py tests/test_api.py -q` | 34 passed. |
| PASS | `python -m pytest tests/test_contract_fixtures.py tests/test_health_summary.py -q` | 8 passed. |
| PASS | `python -m pytest -q` | 265 passed, 1 skipped. |
| PASS | `nox -s lint format_check types --no-install` | Ruff lint/format and mypy passed. |
| PASS | `python -m tools.evaluate_feature_planner` | 10/10 evaluation cases passed; minimum 18/20. |
| PASS | `python -m tools.evaluate_reviewer` | Reviewer corpus passed: 10 cases, 19 findings. |
| PASS | `git diff --check` | No whitespace errors. |
| NOT RUN | Compose, production, physical, edge-canary, external-export checks | Out of scope and not authorized for this pilot. |

## Compatibility checks

The change is additive and has no migration. Existing edge/MQTT/storage consumers are unaffected;
the new API contract is covered through the real FastAPI route and synthetic fixture. No external
consumer of the new endpoint is configured in this repository.

## Safety impact

No production writes, secrets, public export, deployment, hardware, GPIO, Control, Guardrails, or
Executor behavior changed. The endpoint is read-only and has no recovery side effects. Rollback is
reverting the additive route, module, schema, tests, and docs.

## Known limitations

- The summary reports application-observable evidence only; it cannot prove physical, electrical,
  biological, or production-world health.
- Independent human Reviewer Report and final human review notes remain pending.
- The branch/worktree isolation limitation should be resolved by the repository maintainer before
  publishing a PR.

## Documentation changes

`docs/CONTRACTS.md`, `docs/OPERATIONS.md`, and the versioned JSON Schema document the new endpoint,
fields, freshness, status semantics, and non-remediation boundary.

## Manual verification steps

- `NOT RUN`: supervised production/edge/hardware verification; not authorized by the brief.
- `NOT RUN`: human review of the final diff and workflow retrospective; owner is the maintainer.

## Final diff review

Diff is limited to the approved health-summary feature, its versioned fixture/schema, focused tests,
brief, report, and two authoritative documentation updates. No secrets, debug artifacts,
destructive commands, external export, or unrelated refactoring were added.
