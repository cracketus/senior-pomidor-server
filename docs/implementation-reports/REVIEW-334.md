# Review Report: #334 — Pure target capability and interval evaluation

Report schema: `senior-pomidor.review-report.v1`
Reviewer/version: Reviewer 1.0
Reviewer hash: `a41b7e17c90345117daeb909c6303ecfc6e28ee7a2fe154855fea5ddce5e1b92`
Issue/brief: `#334`, `.ai/planning/implementation-brief-334.md`
Base/head: `origin/main` / working tree on `feature/TOMATO-334-map-capability-evaluator`
Audit reference: `.ai/agent-runs/20260909-issue-334-coder.json`

Independence statement: review context was routed separately as `reviewer`; the brief and changed
artifacts were inspected before relying on the implementation report. Review was read-only apart from
this report artifact.

## Verdict

`REQUEST CHANGES`

The additive pure evaluator is scoped safely and the evaluator failure-path coverage was expanded, but
required canonical validation remains unavailable and the aggregate nox command cannot complete its
editable-install stage in the current environment.

## Independent classification

- Task classes: `pure_software`, `schema_data_contract` (the added versioned internal result contract).
- Risk flags: none.
- Differences from brief classification: adding the result contract confirms the brief’s schema/data-contract class; no deployment, hardware, security, or public-contract overlay was found.
- Applicable `SP-FAIL-*`: `SP-FAIL-014` is only partially covered by the Windows-aware matrix and has no dedicated evaluator path test; `SP-FAIL-015` is covered by the existing full test run and package imports.

## Scope and architecture assessment

The changed runtime paths are limited to `app/map/capability.py`, `app/map/evaluator.py`, and additive
exports. The evaluator does not import database, network, State Estimator, Control, API, or hardware
code. No topology YAML, migrations, startup wiring, or physical-action path changed. Documentation
correctly keeps API/UI and real-data activation unimplemented.

## Findings

- id: REV-334-001
  severity: HIGH
  category: tests
  location: docs/implementation-reports/ISSUE-334.md:34
  finding: Required quality and canonical validation evidence is not green.
  evidence: The implementation report records the aggregate nox check as FAIL and canonical validation as FAIL; reviewer reproduction also found `validate_change` did not recognize the task key.
  evidence_excerpt: "| FAIL | `nox -s lint format_check types` | lint/types passed; format session was interrupted after a repeated editable-install hang; local `ruff format --check` passed |"
  impact: The brief requires all selected checks to be recorded and the reviewer verdict rules do not permit approval while required checks are FAIL.
  required_change: Resolve the registered task-key/tooling issue and rerun the full required quality and canonical validation checks to PASS, or record an approved exception outside this implementation.
  suggested_test: Run `nox -s lint format_check types` and `python -m tools.validate_change --base origin/main --task-key tomato-334-map-capability-evaluator --explain --force full`.

## Contract and consumer review

The producer is the Map evaluator; future private API #335 and operator UI #336 are named consumers.
The contract is versioned as `senior-pomidor.map.v1`, frozen, UTC/microsecond based, and uses explicit
percent units plus bounded opaque evidence references. Existing edge, storage, estimator, dashboard,
public export, and hardware contracts are unaffected. No migration or rollout ordering is required.

## Test and evidence matrix

| Status | Required/manual check | Evidence and reviewer assessment |
| --- | --- | --- |
| PASS | focused tests | Exact brief focused command: 87 passed |
| PASS | full pytest | 591 passed, 12 skipped |
| FAIL | `nox -s lint format_check types` | lint/types passed; format session was interrupted during editable-install retry; direct ruff format check passed |
| PASS | `git diff --check` | Clean apart from line-ending warnings |
| FAIL | canonical `validate_change` | Tool reported unknown task key `tomato-334-map-capability-evaluator` |
| PASS | audit artifact | `tools.agent_audit` accepted the bounded coder artifact |
| NOT RUN | independent human review before this run | This report is the first reviewer run; human adjudication remains separate |
| NOT RUN | production, staging, real calibration, hardware, operator UI | Correctly out of scope and prohibited for this review |

## Operations, safety, security and privacy

No startup, deployment, database write, external export, secret, physical action, Guardrails, or
Executor path changed. Rollback is removal of the additive implementation. Evidence refs hash event and
child identities and do not expose raw diagnostics. No production or hardware evidence was requested or
used.

## Documentation assessment

The Map specification and `CURRENT_STATE.md` correctly describe the evaluator as packaged but inactive;
API/UI remain future work. The implementation report accurately discloses the failed checks and pending
review.

## Follow-ups outside this PR

- Register or correct the task key used by `tools.validate_change` before merge.
- Keep API/UI, pagination, concurrency, and real-data activation in their separately scoped briefs.

## Limitations and unverified evidence

- Independent reviewer cannot establish production, staging, hardware, real calibration, or operator UI outcomes.
- Windows-specific evaluator resource/path behavior was not separately exercised; existing full pytest and package checks are not a substitute for that targeted evidence.
