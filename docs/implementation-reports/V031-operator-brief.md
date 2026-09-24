# Implementation Brief: v0.3.1 operator robustness

Status: approved scope via the user request to audit, fix, test and open PRs (2026-09-24).
Planner/version: Codex / repository Coding Agent 1.1.
Approver/date: repository owner, current task, 2026-09-24.
Issue/decision: user release audit; AUDIT-031 is a local task identifier, not a GitHub issue.
Agent run ID / audit artifact: v031-operator / `v031-operator-audit.json` in this directory.

## Problem
Slow API refresh can cancel the awaiting TUI worker while its synchronous HTTP thread continues.
Token files with a conventional final newline fail; non-ASCII tokens can escape the CLI error contract.
Composite views omit stale transport notices for data sourced from other views.

## Desired outcome
One refresh at a time; bounded configuration errors; every displayed cached subview has its own warning.

## Current behavior and evidence
Inspected `app/operator_tui/app.py`, `presenter.py`, `__main__.py`, `app/pomidorctl/config.py`,
`cli.py`, and their tests at fbbf13a7d3444cef73f10697cebba35faa6fe9cc.

## Scope
Operator client configuration, refresh scheduling, composite stale notices, regression tests.
Audit extension: package the existing lifecycle CLI in the runtime image; Dockerfile currently omits it,
so source-free deployment cannot run the documented v0.3.1 lifecycle command.

## Out of scope
Production, hardware, migrations, server response schemas, new operator features.

## Architecture placement
Read-only operator presentation and client configuration retain the existing shared GET client.

## Affected contracts and consumers
CLI configuration errors keep exit 4 and the existing error schema. Token file trailing newline is accepted.
Operator API, edge transport, storage, estimator, control, dashboards and export are unchanged.
CLI and TUI consumers are affected; no wire format, units or timezone changes.

## Safety/risk classification
Task classes: pure_software, infrastructure_deployment. Risk flags: production_availability (no authentication policy or credential storage changes).
SP-FAIL-004: qualify the actual image, not checkout-only imports; SP-FAIL-014: close/clean temporary files; SP-FAIL-015: verify installed entry points.
No production or real hardware access; maintainer owns manual terminal/platform acceptance.

## Proposed implementation sequence
1. Add reproductions for token input, repeated slow refresh and partial failure rendering.
2. Make minimal fixes and run focused/full tests and quality checks.
3. Record evidence and open the requested PR.

## Failure modes
Slow refresh: skip overlapping refresh, preserve current display until completion.
Malformed token: bounded configuration error without token disclosure.
Partial API outage: cached dependent sections explicitly marked stale or disconnected.

## Backward compatibility
Existing valid CLI commands and operator.v1 payloads retained; no server/edge rollout coupling.

## Testing plan
Required: `python -m pytest -q tests/test_pomidorctl.py tests/test_operator_tui.py`,
`python -m pytest -q`, `nox -s lint format_check types`, `git diff --check`.
Required Compose config check and isolated image/rehearsal checks: NOT_RUN locally if Docker is unavailable.
Manual Windows/SSH terminal acceptance: NOT_RUN unless observed. Docker and physical outcomes cannot be inferred.

## Observability
Existing bounded errors and transport banners; no raw response or token logging.

## Documentation updates
TUI refresh behavior and token file format; release procedure corrections in a separate docs PR.

## Rollout and rollback
Merge only after review/CI, then qualify the final immutable candidate. Revert this patch to roll back;
no data or schema rollback. No deployment performed.

## Acceptance criteria
- Slow repeated refresh requests complete one fetch without overlap or starvation.
- Token file LF/CRLF works; invalid header characters produce exit 4 without secret output.
- Composite views display transport notices for cached dependent views.
- Both TUI entry points validate refresh bounds and CLI format flags consistently.

## Blocking open questions
None for software fixes. Exact release qualification remains a separate gate.

## Evidence and references
`tests/test_pomidorctl.py`, `tests/test_operator_tui.py`, `docs/OPERATOR_TUI.md`.
Production and physical state were not inspected.
