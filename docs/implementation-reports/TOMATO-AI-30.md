# Implementation Report: Documentation ownership map

Issue/brief: #150 / `.ai/implementation-briefs/TOMATO-AI-30-doc-ownership.md`

Branch/worktree: `feature/TOMATO-AI-135-shared-context` / existing worktree; unrelated pre-existing
untracked `.pytest-temp-tomato-ai-final/` and TOMATO-AI-31–33 draft briefs preserved.

Task classes and risk flags: `pure_software`, `schema_data_contract`; `public_contract`

Applicable `SP-FAIL-*` IDs: `SP-FAIL-009`, `SP-FAIL-010`, `SP-FAIL-011`, `SP-FAIL-014`

## Implemented behavior

- Added versioned `docs_map_v1` ownership map covering schemas/models, API/storage, Compose/deploy,
  State Estimator, future control boundaries, hardware adapters, and public README/status.
- Added fail-closed validation for malformed maps, missing owners, unsafe paths, unknown enum values,
  missing authoritative documents, duplicate IDs, and authority conflicts.
- Added deterministic `docs_map_coverage_v1` JSON output for supplied source paths. Unknown paths
  keep the command unsuccessful and are never silently assigned.
- Added mechanical/semantic mapping fixtures and focused tests.
- Updated the approved #150 brief metadata to record user approval on 2026-08-10.

## Files changed and purpose

- `docs-map.yaml`: versioned source-path ownership map and named checks/consumers.
- `tools/docs_map.py`: read-only YAML validator, coverage reporter, and bounded CLI.
- `tests/test_docs_map.py`: happy and failure-path tests for coverage and authority behavior.
- `tests/fixtures/docs_map/*.yaml`: synthetic missing-owner, conflict, unknown-path, and
  mechanical/semantic fixtures.
- `.ai/implementation-briefs/TOMATO-AI-30-doc-ownership.md`: approval metadata.
- `docs/implementation-reports/TOMATO-AI-30.md`: this implementation evidence.

## Design decisions

- Conflicting ownership is rejected rather than resolved by source-code recency or document recency;
  this preserves the approved no-truth-selection boundary.
- Future Control/Guardrails/Executor paths are represented as `future`/`future_boundary_only` map
  entries and do not create runtime components or grant actuation authority.
- Coverage accepts explicit source paths so callers control the read-only input set; no implicit
  repository-wide scan or external access is performed.
- Reports are JSON, sorted, bounded, and secret-safe; no source contents or environment values are
  emitted.

## Deviations from brief

None. The brief's open question about exact owners was addressed using repository-maintainer role
labels and remains a human governance choice for future map revisions; no private or external owner
was invented.

## Tests added

- Repository map validation and seven-area coverage.
- Unknown source path fail-closed coverage.
- Missing owner rejection.
- Duplicate source authority conflict rejection without truth selection.
- Explicit mechanical versus semantic mapping behavior.

## Commands run and results

| Status | Command | Result/evidence |
| --- | --- | --- |
| PASS | `python -m pytest -q tests/test_docs_map.py` | 5 passed. |
| PASS | `python -m pytest -q` | 281 passed, 1 skipped. |
| PASS | `ruff check tools/docs_map.py tests/test_docs_map.py` | All checks passed. |
| PASS | `ruff format --check tools/docs_map.py tests/test_docs_map.py` | Changed files already formatted. |
| PASS | `nox -s lint format_check types` (lint/types sessions) | lint and types sessions successful. |
| FAIL | `nox -s lint format_check types` (format_check session) | Existing unrelated `tests/test_github_workflow_conventions.py` is unformatted; file not changed by this task. |
| PASS | `python -m tools.evaluate_feature_planner` | 10/10 revision cases, minimum 18/20. |
| PASS | `git diff --check` | No whitespace errors. |
| PASS | `python -m tools.docs_map --map docs-map.yaml --root . --source-path app/models.py --source-path docker-compose.yml --source-path app/control.py` | Valid map; 100% coverage; no unknown paths. |

## Compatibility checks

`docs_map_v1` and `docs_map_coverage_v1` are additive governance artifacts. Existing runtime,
database, API, MQTT, edge, dashboard, export, Compose, and hardware behavior is unchanged. The
exact external edge repository consumer set remains unknown and is represented as map impact rather
than inferred facts.

## Safety impact

No production, secrets, public-data writes, physical action, Guardrails/Executor, external export,
or deployment behavior was accessed or changed. The validator only reads map/repository inputs and
emits bounded local JSON when requested. Rollback is removal/disablement of the map/tool/tests and
generated reports; durable runtime data is untouched.

## Known limitations

- Coverage is only complete for the source paths supplied by the caller; omitted paths are not claimed
  covered. Owner and cross-repository impact values require maintainer review.
- `nox format_check` remains red because of an unrelated pre-existing formatting issue; owner is the
  development maintainer and this task did not reformat that file.

## Documentation changes

Added the machine-readable map and its implementation report. Existing contract, operations, public,
and hardware documentation was not semantically rewritten.

## Manual verification steps

- Production deployment/write: `NOT RUN` — outside scope.
- Physical hardware/wiring: `NOT RUN` — CI cannot prove physical outcomes.
- External edge-consumer coordination: `NOT RUN` — consumer repository unavailable.
- Human authority/owner review: `NOT RUN` — requires maintainer review of the map entries.

## Final diff review

The final worktree review found only the approved #150 files plus the previously present untracked
draft briefs and pytest temp directory. No secrets, debug artifacts, runtime changes, weakened
assertions, production paths, or destructive operations were introduced.
