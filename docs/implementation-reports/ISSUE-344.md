# Implementation Report: deterministic State Estimator comparison runner

Issue/brief: [#344](https://github.com/cracketus/senior-pomidor-server/issues/344)

Agent run ID / audit artifact: `20260910-issue-344-coder` /
`.ai/agent-runs/20260910-issue-344-coder.json`

Branch/worktree: `feature/TOMATO-AI-344-state-estimator-demo-runner` /
isolated task worktree `tomato-ai-344-state-estimator-demo-runner`

Task classes and risk flags: `pure_software`, conservatively `infrastructure_deployment` because the runtime
image packages the CLI and synthetic fixtures; no risk flags.

Applicable `SP-FAIL-*` IDs: `SP-FAIL-014`, `SP-FAIL-015`.

## Implemented behavior

- One offline command compares `normal_two_pods` and `hot_high_vpd` in a compact deterministic table.
- A public Python replay-evaluation helper returns state, sensor health, anomalies, diagnostics, Guardrails, and
  advisory action simulation without changing the existing HTTP replay contract.
- Fixture timestamps drive evaluation by default; `--at` accepts an explicit timezone-aware clock.
- `--json` emits sorted, byte-stable evidence with source path and SHA-256 identity. It declares and omits the
  runtime-only `diagnostics.processing_ms` field.
- `--view timeline` exposes every accumulated replay frame. `--details` adds sorted Guardrail and action reasons.
- Registered missing-probe, unavailable-input, and impossible-jump fixtures are supported diagnostically.
- Unknown/malformed input fails with a non-zero exit and no traceback. Anomaly or blocked scenario results remain
  successful evaluations.
- Every action result is checked before rendering; physical actuation and watering must both remain false.
- The application image packages only the runner support files and existing sanitized fixtures needed by the
  documented Compose command.

## Files changed and purpose

- `app/state_estimator/replay.py`: add the public complete evaluation helper while preserving `replay_observations`.
- `tools/demo_state_estimator.py`: deterministic offline CLI and human/JSON renderers.
- `tests/state_estimator/test_demo_runner.py`: happy, temporal, deterministic, malformed, offline, packaging, and
  advisory-safety coverage.
- `Dockerfile`: package the runner and existing synthetic State Estimator fixtures in the runtime image.
- `docs/STATE_ESTIMATOR_DEMO.md`: commands, timing, evidence capture, interpretation limits, and fallback procedure.
- `README.md`: link the focused demo guide.
- `.ai/agent-runs/20260910-issue-344-coder.json`: bounded sanitized implementation audit record.
- `docs/implementation-reports/ISSUE-344.md`: implementation and verification handoff.

## Design decisions

- Keep the issue's flag-based CLI rather than introduce subcommands; the presentation command stays exactly one
  invocation while timeline and JSON remain optional views.
- Render normalized canonical measurements rather than parse raw fixture fields again. Domain thresholds,
  transformations, anomaly decisions, Guardrails, and sampling decisions remain production-owned.
- Preserve complete runtime diagnostics in the Python helper, but remove `processing_ms` only at the deterministic
  evidence serialization boundary.
- Sort scenarios by an explicit presentation order so the baseline stays first even when CLI arguments are reversed.
- Use registered repository fixtures only; arbitrary paths and production data are not accepted.
- Preserve current estimator semantics even where diagnostic results may merit later policy review.

## Deviations from brief

- None. The optional timeline and detail views use the same bounded replay results and remain within the requested
  diagnostic/output scope.

## Tests added

- Normal has no false environmental anomaly; hot/high-VPD emits current `HIGH_TEMP` and `HIGH_VPD` warnings.
- Human output separates evidence layers and obtains values from current production results.
- Repeated JSON and human rendering are stable; runtime processing duration is excluded only from JSON evidence.
- Fixture and explicit clocks control Guardrail/action timestamps.
- All registered diagnostic scenarios run without physical actuation.
- Malformed and unknown scenarios fail clearly and non-zero.
- Patched network and SQLAlchemy execution boundaries prove the offline call path performs neither operation.
- Dockerfile packaging and all registered fixture paths are checked.

## Commands run and results

| Status | Command | Result/evidence |
| --- | --- | --- |
| PASS | `/tmp/sp344-venv/bin/python -m pytest -q tests/state_estimator/test_demo_runner.py tests/state_estimator/test_config_replay.py` | 19 passed. |
| PASS | `/tmp/sp344-venv/bin/python -m pytest -q -k 'not test_production_overlay_forces_production_mode_without_new_env_file_field'` | 613 passed, 2 skipped, 1 Docker-dependent test deselected. |
| FAIL | `/tmp/sp344-venv/bin/python -m pytest -q` | 613 passed and 2 skipped; one pre-existing Compose test could not invoke the absent `docker` executable. No product assertion failed. |
| PASS | `/tmp/sp344-venv/bin/nox -s lint format_check types` | Ruff lint/format and mypy passed for the complete repository. |
| PASS | `git diff --check` | No whitespace errors. |
| PASS | `/tmp/sp344-venv/bin/python -m tools.agent_audit .ai/agent-runs/20260910-issue-344-coder.json` | Audit artifact validated and aggregated. |
| PASS | documented CLI comparison, timeline, JSON parse, `--help`, and `--list-scenarios` | Commands completed; JSON contained two scenarios with one and two frames. |
| NOT_RUN | `python -m tools.agent_task compose tomato-ai-344-state-estimator-demo-runner config` | The environment has no `docker` executable; Compose rendering and container execution were not possible. |
| FAIL | `/tmp/sp344-venv/bin/python -m tools.validate_change --base origin/main --task-key tomato-ai-344-state-estimator-demo-runner --force full` | Focused tests passed; canonical wrapper injected the task Compose name into staging tests, had no Docker, and could not find `nox` in its sanitized PATH. Direct selected checks are recorded above. |

## Compatibility checks

- Existing `replay_observations` signature, return shape, fixture behavior, and HTTP replay contract are unchanged.
- Existing replay tests and the complete non-Docker suite pass.
- Linux path behavior passed. Paths use `pathlib`, files are read with closing convenience methods, and no package
  discovery rule changed; Windows execution remains unverified.
- Runtime-image file presence is statically covered. An actual image build/Compose execution remains unverified.

## Safety impact

- Offline and read-only: no production access, database mutation, network call, external export, credentials,
  Executor, GPIO, sensor hardware, or actuator adapter.
- The CLI consumes sanitized synthetic fixtures only and rejects any result that proposes physical actuation or
  watering.
- Rollback is a revert of this branch commit; there is no migration, durable-data change, or deployment action.

## Known limitations

- Docker image build and `docker compose exec` are `NOT_RUN` in this environment.
- Real operating evidence and biological validity are explicitly outside this synthetic runner.
- Current production semantics can report a GOOD aggregate data-quality score while Guardrails block a configured
  missing soil probe; the runner preserves and exposes this rather than changing policy in #344.

## Documentation changes

- `docs/STATE_ESTIMATOR_DEMO.md` documents host/Compose use, expected duration, synthetic-vs-real evidence,
  interpretation limits, deterministic JSON capture, and prerecorded fallback.
- `README.md` links the focused guide.

## Manual verification steps

- `NOT_RUN` (release/operator): build the exact application image, start an isolated stack with external export and
  hardware disabled, run the documented `docker compose exec` comparison, capture JSON twice, and compare bytes.
- `NOT_RUN` (presenter): verify the table fits the screen-sharing terminal and rehearse the two-minute explanation.
- `NOT_RUN` (physical/biological): not applicable to synthetic software behavior and cannot be inferred from CI.

## Final diff review

- The isolated worktree began clean and contains no unrelated edits.
- No secrets, private paths, production payloads, debug artifacts, threshold copies, weakened assertions, contract
  drift, database writes, network calls, or actuation paths were found.
- Existing fixtures are reused without modification; runtime packaging adds only sanitized demo inputs.
