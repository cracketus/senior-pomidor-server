# Implementation Report: v0.3.1 release documentation audit

Issue/brief: user-authorized 2026-09-24 audit/fix/PR request; documentation of existing behavior and
candidate acceptance only. No release, deployment or evidence PASS was authorized or performed.
Agent run ID / audit artifact: v031-release-docs / [v031-release-docs-audit.json](v031-release-docs-audit.json).
Branch/worktree: `fix/AUDIT-032-release-runbooks`, isolated checkout from `fbbf13a`, rebased onto merged Core `0a0832e`.
Task class: pure_software (documentation plus its assertion test). Risk flags: none.
The existing regression test now requires explicit rollback-SHA input and validation instead of a
hard-coded historical SHA. Runtime behavior is unchanged.
Relevant failures: SP-FAIL-004 candidate identity; SP-FAIL-005 recovery evidence; SP-FAIL-015 packaging.

## Implemented behavior

Runbooks accept explicit campaign identities instead of executing historical v0.3.0 pins.
Rollback is checked against actual installed baseline, not an assumed version. Production PowerShell
uses 7.3+ native failure handling; Bash stops on failed commands. Lifecycle mutation flags are distinguished
from read-only show. Source-free bundle, API image and operator TUI installation are separated.

## Files changed and purpose

Release/qualification/install runbooks: identity and command corrections.
OPERATIONS: current HTTP ACK authority, lifecycle modes, dynamic rollback.
OPERATOR_TUI: extra dependency and refresh behavior supplied by the paired code PR.
CURRENT_STATE/README: TUI and Map API status, historical pin labels.
V031_RELEASE_READINESS: dated findings, verified baseline CI and remaining gates.

## Design decisions

Keep existing detailed safety and staging procedures. Replace hard-coded candidate data with explicit
inputs and checks; do not fabricate digests or turn baseline CI into new-candidate evidence.

## Deviations from brief

None within the requested documentation audit. Runtime fixes are a separate PR.

## Tests added

Adjusted the rollback documentation test to require operator input, full SHA validation and native
PowerShell error propagation, retaining bundle/installed-identity assertions.

## Commands run and results

| Status | Command/check | Evidence |
| --- | --- | --- |
| PASS | `git diff --check` | No whitespace errors |
| PASS | Local Markdown links | All targets in changed Markdown resolved; fixed promotion gate link |
| PASS | `bash -n` on unindented fenced Bash examples | 40 blocks parsed; commands not executed |
| PASS | `python -m tools.ai_context_docs` | Generated summaries current |
| PASS | `python -m pytest -q tests/test_release_assets.py tests/test_ai_context_docs.py tests/test_docs_map.py` | 24 passed after rebase onto merged Core |
| FAIL (environment) | `python -m pytest -q` | 672 passed, 2 skipped; one failure because Docker executable is absent |
| PASS | `nox --envdir ../server/.nox -r --no-install -s lint format_check types` | Reused isolated check environments |
| NOT_RUN | PowerShell execution, Docker, release/staging/installation | No target execution; syntax/path review only |

## Compatibility checks

Command/module paths checked against current code. Docs describe the paired fixes but do not change
API, migrations, runtime configuration or payloads. The documentation assertion test was updated.

## Safety impact

No mutation of production, repository settings, artifacts, devices or data. All deployment gates remain.

## Known limitations

PowerShell native execution and staging/hardware validation remain operator-owned. A valid Markdown
example is not installation evidence. The paired operator/image patch is merged and post-merge CI passed; final artifact qualification remains.

## Documentation changes

See [candidate audit and checklist](../ru/V031_RELEASE_READINESS.md).

## Manual verification steps

Follow the revised sequence with one accepted identity pair: exact-SHA CI, published bundle, real
compatibility, soak, backup/restore, rollback and separately approved canary. All remain NOT_RUN here.

## Final diff review

Only the documentation assertion test changed alongside Markdown/audit metadata; no runtime files changed. No copied secrets, production logs or invented release identities.
