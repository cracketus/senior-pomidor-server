# Implementation Report: GitHub agent workflow conventions

Issue/brief: [#131](https://github.com/cracketus/senior-pomidor-server/issues/131)

Branch/worktree: `feature/TOMATO-AI-11-agent-workflow-conventions` / isolated agent task

Task classes and risk flags: `infrastructure_deployment`, `pure_software` / `production_availability`

Applicable `SP-FAIL-*` IDs: `SP-FAIL-001`, `SP-FAIL-002`, `SP-FAIL-003`, `SP-FAIL-004`, `SP-FAIL-014`, `SP-FAIL-015`

## Implemented behavior

- Added five English GitHub issue forms for feature, bug/incident, schema, infrastructure, and edge/hardware work.
- Added an English pull request template requiring issue/brief links, scope, contract and safety impact, exact evidence status, reports, rollback, and human approval.
- Documented labels, Planner/Coder/Reviewer lifecycle, examples, follow-up handling, and safety boundaries.
- Added regression tests for template presence and required workflow gates.

## Files changed and purpose

- `.github/ISSUE_TEMPLATE/*.yml`: structured issue forms and required evidence fields.
- `.github/pull_request_template.md`: PR evidence and approval checklist.
- `docs/GITHUB_AGENT_WORKFLOW.md`: canonical lifecycle, label taxonomy, examples, and boundaries.
- `tests/test_github_workflow_conventions.py`: template/documentation regression checks.

## Design decisions

- Labels are documented as a taxonomy and templates reuse only the labels needed for their workflow; label creation is a GitHub metadata operation and is not required for local safety.
- Templates require an Implementation Brief link before coding while allowing a planning issue to remain unlinked during `needs-planning`.
- Manual, physical, deployment, and rehearsal evidence remain explicitly `NOT RUN` until a human records them.

## Deviations from brief

None.

## Tests added

- Template inventory and required brief/acceptance fields.
- PR evidence/approval gate presence.
- Lifecycle and safety-boundary documentation presence.

## Commands run and results

| Status | Command | Result/evidence |
| --- | --- | --- |
| PASS | `python -m pytest -p no:cacheprovider -q tests/test_github_workflow_conventions.py` | 3 passed; cache provider omitted because the pre-existing worktree cache is ACL-protected on Windows. |
| PASS | `python -m pytest -p no:cacheprovider -q` | 260 passed, 1 skipped. |
| PASS | `python -c "import yaml, pathlib; ..."` | All five issue-form YAML files parsed successfully. |
| PASS | `nox -s lint --no-install` | Ruff checks passed. |
| PASS | `nox -s format_check types --no-install` | Formatting and mypy passed during the final quality run. |
| PASS | `$env:APP_IMAGE='senior-pomidor-server:ci'; docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile observability --profile daily-story config --quiet` | Read-only Compose render passed; no services were started or mutated. |
| PASS | `git diff --check` | No whitespace errors. |

## Compatibility checks

Only GitHub metadata/templates and documentation are changed. Runtime services, schemas, durable data,
edge consumers, and public APIs are unaffected. GitHub issue forms use the supported YAML form syntax.

## Safety impact

No production writes, secrets, deployment, external export, hardware, GPIO, Guardrails, or Executor
behavior changed. Compose validation was read-only. Rollback is reverting this single documentation/
metadata commit.

## Known limitations

Actual label creation/reconciliation in GitHub remains a maintainer-owned metadata step and must reuse
existing labels rather than create duplicates. Physical and production rehearsal evidence is `NOT RUN`.

## Documentation changes

`docs/GITHUB_AGENT_WORKFLOW.md` is the canonical lifecycle and evidence narrative; templates link the
existing `.ai` brief/report contracts.

## Manual verification steps

- `NOT RUN`: a maintainer should inspect the rendered issue forms and PR template in GitHub after merge.
- `NOT RUN`: a maintainer should reconcile the documented label taxonomy with the repository's current labels.

## Final diff review

Diff is limited to the five issue forms, PR template, workflow documentation, implementation report,
and focused tests. No secrets, debug artifacts, runtime code, or destructive operations are included.
