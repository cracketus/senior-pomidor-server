# Implementation Report: watchdog/spool-aware server health semantics

Issue/brief: Human-approved implementation plan for server issue #227.

Agent run ID / audit artifact: `20260824-issue-227-coder` /
`.ai/agent-runs/20260824-issue-227-coder.json`.

Branch/worktree: `feature/ISSUE-227-watchdog-spool-health` /
`.agent-worktrees/issue-227-watchdog-spool-health`.

Task classes and risk flags: `pure_software`, `schema_data_contract`,
`edge_hardware_integration`; `edge_server_compatibility`, `public_contract`.

Applicable `SP-FAIL-*` IDs: `SP-FAIL-009`, `SP-FAIL-011`, `SP-FAIL-014`.

## Implemented behavior

- Added a pure deterministic evaluator for normalized watchdog, spool, and application diagnostics with
  `ALERT > WARN > UNKNOWN > OK` precedence and ordered, deduplicated findings.
- Added only `WARN` and `ALERT` reliability findings to existing latest/history `health_alerts`, using
  fixed metrics, reason codes, levels, and messages. Unknown legacy state remains alert-free.
- Added `components.edge_reliability` only to node-scoped `health_summary_v1`, including bounded safe
  subsystem projections and telemetry age. Missing, stale, timestamp-invalid, or DB-unavailable
  telemetry produces `UNKNOWN` without evaluating old values.
- Deduplicated summary reason codes in deterministic order and retained the global 20-reason limit.
- Preserved existing endpoint paths, database storage, telemetry schema, server-only summary behavior,
  existing alert shapes, and the `health_summary_v1` version.

## Files changed and purpose

- `app/edge_reliability.py`: shared pure evaluator and reliability alert projection.
- `app/telemetry.py`, `app/health_summary.py`: private API and summary integrations using one evaluation.
- `app/daily_story.py`: accepts and groups additive alert reason codes.
- `docs/schemas/health-summary-v1.schema.json`, `tests/fixtures/contracts/health_summary_v1.json`:
  additive component contract and compatibility fixture.
- `tests/test_edge_reliability.py`, API/summary/contract/consumer tests: mapping, precedence, freshness,
  compatibility, bounded ordering, and privacy regressions.
- `docs/CONTRACTS.md`, `.ai/CURRENT_STATE.md`, `CHANGELOG.md`: contract, current-state, and release notes.
- `.ai/agent-runs/20260824-issue-227-coder.json`: bounded audit record.

## Design decisions

- Centralized every state mapping and fixed message in the evaluator; neither API nor summary owns a
  second mapping table.
- Kept unknown findings in private summary diagnostics but filtered them from legacy `health_alerts`.
- Projected only state/result/booleans and reported spool states into the private summary. Raw edge
  reason/error details, paths, service names, boot IDs, and counters are excluded.
- Used the existing telemetry freshness threshold because no edge heartbeat-specific interval is part
  of this contract.

## Deviations from brief

- The requested validator task key `ISSUE-227` is not a valid registry key; the exact invocation failed
  before running checks. Validation passed with the generated isolated key
  `issue-227-watchdog-spool-health`, including `--force full`.
- No behavior or scope deviation.

## Tests added

- Table-driven known/unknown watchdog, spool, and application mappings, simultaneous findings,
  deduplication, fixed messages, configured-disabled state, and severity precedence.
- Latest/history API alert shape and preservation of existing numeric alert shape.
- Healthy, legacy/missing, stale, DB-failure, server-only, and bounded summary behavior.
- Schema validation/round trip and daily-story/AI additive reason-code acceptance.
- Public status and Grafana Cloud exclusion of reason codes, raw results, IDs, service names, and counters.

## Commands run and results

| Status | Command | Result/evidence |
| --- | --- | --- |
| PASS | `python -m pytest tests/test_edge_reliability.py tests/test_api.py tests/test_health_summary.py tests/test_contract_fixtures.py tests/test_daily_story.py tests/test_ai_analysis.py tests/test_public_status.py tests/test_grafana_cloud_exporter.py -q` | 133 passed before final fail-safe review; the post-review cache-disabled rerun passed 134 tests. |
| PASS | `python -m pytest -q` | 408 passed, 3 skipped before final fail-safe review; the post-review cache-disabled rerun passed 409 tests, 3 skipped. |
| PASS | `nox -s lint format_check types` | Ruff lint/format and mypy passed. |
| PASS | `git diff --check` | No whitespace errors; Git emitted only line-ending normalization warnings. |
| FAIL | `python -m tools.validate_change --base origin/main --task-key issue-227-watchdog-spool-health --explain --force full` | Focused 134, full 409/3 skipped, quality, and diff checks PASS; overall exit 1 because maturity gate reports `missing audit record` despite the validated audit artifact being present. |
| NOT RUN | Manual edge canary | Requires operator-observed private API checks on a real edge node. |

An earlier quality attempt failed because two accidentally concurrent local `nox` processes contended
for the same Windows `.nox/types` environment. Only those task-created processes were stopped; the exact
command then passed sequentially.
The final focused command completed all tests but hit the known Windows `.pytest_cache` ACL failure
(`SP-FAIL-014`) during session teardown; immediate `-p no:cacheprovider` reruns passed focused and full.
The task registry contains the implementation brief, approval, evidence, classifications, and risk
references. The current validator calls the maturity evaluator with `audit_record=None`, so a change that
adds the required audit artifact cannot clear that gate; this tooling issue was not changed outside scope.

## Compatibility checks

- Legacy telemetry without reliability blocks produces no reliability alert and an `UNKNOWN` scoped
  component, never false `OK`.
- Current telemetry fixture and health-summary fixture validate and serialize through the real test
  boundaries. Latest/history, daily story, AI analysis, public status, and Grafana export are covered.
- Server-first rollout needs no edge schema or database migration. Public status may degrade from the
  increased private alert count, but exposes neither codes nor reliability payloads.

## Safety impact

- Read-only deterministic evaluation only. No recovery decisions, restarts, reboot, actuator path,
  production access/write, deployment, Compose mutation, secret access, external export, or migration.
- Rollback is the previous application image; existing JSONB remains compatible and needs no cleanup.

## Known limitations

- A live edge/PostgreSQL canary remains manual. Automated tests cannot prove real watchdog/systemd/spool
  behavior or physical-world reliability.
- Canonical maturity handoff remains `FAIL` because `tools.validate_change` does not load the task's audit
  artifact. All executable selected checks passed; a maintainer must resolve or waive the tooling defect.

## Documentation changes

- `docs/CONTRACTS.md` defines mappings, unknown/freshness behavior, projections, limits, consumers, and
  public/export privacy boundaries.
- `docs/schemas/health-summary-v1.schema.json` keeps v1 and adds the optional node-scoped component.
- `.ai/CURRENT_STATE.md` and `CHANGELOG.md` record the deployable behavior.

## Manual verification steps

- `NOT_RUN`: after server-first rollout, inspect one node-scoped private summary and latest/history for
  healthy, recovering, suppressed, and legacy/missing telemetry. Separately verify server-only summary.
  Abort on healthy WARN/ALERT, suppression `OK`, legacy false-health, changed existing alert objects, or
  private reliability fields in public/export output.

## Final diff review

- Unrelated changes were absent. The diff was reviewed for edge-provided text leakage, duplicate mapping
  tables, stale-data evaluation, unbounded reasons, schema/version drift, public/export leakage, secrets,
  debug artifacts, database changes, and rollback gaps.
