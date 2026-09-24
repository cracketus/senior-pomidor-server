# Implementation Report: v0.3.1 operator and runtime packaging fixes

Issue/brief: [approved task scope](V031-operator-brief.md), user request 2026-09-24.
Agent run ID / audit artifact: v031-operator / [v031-operator-audit.json](v031-operator-audit.json).
Branch/worktree: `fix/AUDIT-031-operator-release`; clean isolated clone from `fbbf13a`.
Task classes: pure_software, infrastructure_deployment. Risk: production_availability (image packaging).
Applicable failures: SP-FAIL-004, SP-FAIL-014, SP-FAIL-015.

## Implemented behavior

- Slow TUI refresh completes without cancellation or overlapping batches from timer/manual refresh.
- Composite overview/plant sections expose dependent-view transport failure and cached-data warnings.
- CLI token files accept a final LF/CRLF, are read with an 8 KiB bound, and reject invalid header characters.
- CLI rejects interactive TUI with JSON/verbose; module entry point uses the same argument validation.
- Existing lifecycle administration CLI is copied into the runtime image.

## Files changed and purpose

`app/operator_tui/`: scheduling, entry point and composite status presentation.
`app/pomidorctl/`: bounded configuration and output-mode validation.
`Dockerfile`: package existing lifecycle module; `tests/`: regression coverage and image smoke assertion.

## Design decisions

Keep the canonical synchronous GET client and strict operator.v1 validation. Skip refresh requests while
one is active; cancelling an asyncio wait cannot cancel its underlying HTTP thread. No schema change.
The lifecycle command retains its existing explicit mutation guards; packaging does not invoke it.

## Deviations from brief

The audit discovered missing lifecycle packaging after operator review. Scope was recorded in the brief
before the Dockerfile change, within the user's requested release-blocker audit/fix authorization.

## Tests added

Slow repeated refresh; partial failure in composite views; token LF/CRLF and malformed header values;
shared TUI argument validation; runtime module inclusion; actual container lifecycle help in Docker E2E.

## Commands run and results

| Status | Command | Evidence |
| --- | --- | --- |
| PASS | `python -m pytest -q tests/test_pomidorctl.py tests/test_operator_tui.py` | 33 passed |
| PASS | `python -m pytest -q tests/state_estimator/test_demo_runner.py tests/test_release_assets.py` | Packaging/runner checks passed |
| FAIL (environment) | `python -m pytest -q` | 685 passed, 2 skipped, 1 failed: docker executable absent |
| PASS | `nox -s lint format_check types` | All three sessions passed |
| PASS | `git diff --check` | Clean |
| NOT_RUN | Compose config, Docker E2E, exact-image lifecycle smoke | Docker absent locally; added E2E gate must pass in CI |
| NOT_RUN | Windows/SSH acceptance, staging/rollback, physical acceptance | No target environment or hardware used |

An initial `nox --no-venv` invocation was rejected by Nox because sessions install dependencies;
the canonical isolated Nox command above was subsequently run successfully.

## Compatibility checks

Existing operator/API tests and full software suite passed apart from the Docker environment prerequisite.
No Edge wire format, persistent schema, physical command or exporter change. Python 3.12 tested locally.

## Safety impact

No production access, deployment, real hardware, migrations or exports. Revert the patch to roll back;
no data restoration or schema downgrade. An active HTTP request remains bounded by the configured timeout.

## Known limitations

Docker/rehearsal evidence is outstanding. Green baseline CI is not PR-head CI. Distribution metadata still
says 0.1.0; release identity is Git tag/REVISION/OCI digest. Exact release qualification must follow merge.

## Documentation changes

This brief/report record code evidence. Operational documentation is in the separate release-runbooks PR.

## Manual verification steps

Maintainer: exercise 80x24/60x18 terminals, six views, slow/unavailable/recovered API, then qualify final
Core/Edge images and rollback in isolated staging. All manual results remain NOT_RUN.

## Final diff review

Changes bounded to operator behavior, missing runtime module and regressions. No secret/config payloads,
production writes, Guardrails changes, data migrations or unrelated source edits.
