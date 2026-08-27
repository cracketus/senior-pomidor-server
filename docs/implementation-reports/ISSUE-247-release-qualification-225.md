# Implementation Report: release qualification foundation for epic #225

Issue/brief: #247 / #260; `.ai/implementation-briefs/ISSUE-247-release-qualification-225.md`.

Agent run ID / audit artifact: `20260826-issue-247-coder` /
`.ai/agent-runs/20260826-issue-247-coder.json`.

Branch/worktree: `feature/TOMATO-247-release-qualification-225` / isolated agent task
`tomato-247-release-qualification-225`, based on `c71d019f5d5511899b6134c7bc57ebf867d61755`.

Task classes and risk flags: `pure_software`, `schema_data_contract`, `infrastructure_deployment`,
`edge_hardware_integration`; `security_secrets`, `edge_server_compatibility`, `production_availability`,
`public_contract`.

Applicable `SP-FAIL-*` IDs: `SP-FAIL-001`, `SP-FAIL-002`, `SP-FAIL-003`, `SP-FAIL-004`, `SP-FAIL-006`,
`SP-FAIL-007`, `SP-FAIL-008`, `SP-FAIL-014`, `SP-FAIL-015`, `SP-FAIL-017`.

## Implemented behavior

- Added strict v1 schemas, sanitized templates, semantic validation, identity checks, and deterministic generation
  for system-invariant, Edge/Core compatibility, and release-validation evidence. Required RC evidence fails
  closed on missing, failed, synthetic, wrong-scope, impossible-count, identity-drift, or `NOT_RUN` input.
- Formalized stable `sp-inv-001..008` definitions and test mappings. Current persistence, idempotency,
  observation-time, fail-safe health, compatibility, and privacy assertions execute in CI; future actuator
  invariants remain explicitly `NOT_IMPLEMENTED`.
- Added a separately named PR `docker-e2e` job. Its isolated test covers migrations/readiness/worker health,
  HTTP plus MQTT duplicate/lost-ACK semantics, normalized PostgreSQL persistence, latest/history/health/operator
  consumers, State Estimator, Grafana provisioning, read-only datasource permissions, and four reliability alert
  firing/non-firing/no-data/recovery query transitions with bounded logs and task-owned cleanup.
- Added manually dispatched RC jobs named `system-invariants`, `edge-core-e2e`, and `release-validation`, bound to
  exact Core/Edge SHAs and digests. Real Edge/staging/canary results are validated, never synthesized.
- Added the server #202 staging boundary: staging accepts only the reserved device prefix, production rejects it,
  and HTTP/photo/MQTT enforce the rule before persistence. The persistent overlay uses an exact image, isolated
  credentials, topic, database, paths, project, loopback ports, labels, and disabled external export. The
  production overlay forces production mode even when an older runtime env file lacks the new setting.
- Added temporal-integrity tests for delayed/out-of-order replay, duplicate receive time, exact freshness boundary,
  invalid/future timestamps, and the Europe/Vienna DST fold.
- Created P0 child #260 under umbrella #247 and corrected stale #228/#229 child checkboxes in open epic #225.

## Files changed and purpose

- `.github/workflows/ci.yml`, `.github/workflows/release-qualification.yml`: required PR and fail-closed RC jobs.
- `tools/release_qualification.py`: bounded report generator, schema/semantic/privacy and identity validator.
- `docs/schemas/*.json`, `docs/system-invariants-v1.yaml`, `tests/fixtures/release_qualification/`: versioned
  contracts, stable catalogue, and deliberately non-qualifying templates.
- `tests/test_release_qualification.py`, `tests/test_temporal_integrity.py`: contract, invariant, privacy,
  compatibility, ordering, clock, and negative-gate coverage.
- `tests/test_docker_e2e.py`, `docker-compose.e2e.yml`, `tests/test_github_workflow_conventions.py`: expanded
  stack path, test-only fast evaluator provisioning, and CI contract.
- `app/environment_boundary.py`, `app/config.py`, `app/api.py`, `app/mqtt_worker.py`: explicit deployment identity
  boundary without changing production response schemas.
- `docker-compose.staging.yml`, `deploy/senior-pomidor-staging.env.example`, `docker-compose.yml`,
  `docker-compose.prod.yml`, `deploy/senior-pomidor.env.example`: isolated staging topology and forced production
  mode.
- `docs/STAGING.md`, `docs/CONTRACTS.md`, `docs/OPERATIONS.md`, `docs/release-evidence/README.md`,
  `.ai/CURRENT_STATE.md`: authoritative contract, staging, qualification, evidence, and current-state guidance.

## Design decisions

- Real Edge/Core, soak, rehearsal, rollback, canary, and production outcomes enter only through sanitized reports
  from authorized operators. A server fixture cannot become release evidence by changing only its aggregate status.
- System-invariant generation executes real in-memory persistence and current builders but does not pretend that
  SQLite or fixtures prove Docker, Edge, or physical behavior.
- The staging/production identity boundary is additive and mode-gated. Development and rehearsal retain existing
  fixture compatibility; production HTTP response shapes and telemetry schemas remain unchanged.
- Staging port lists override base ports rather than merge them. Rendered evidence contains only the four assigned
  loopback ports and no production path or external network.
- Docker cleanup activates all task project profiles for `down --remove-orphans`, uses a bounded container-removal
  wait, then an offline helper only
  to normalize permissions under the verified temporary bind root before host deletion; it never uses `down -v`
  or deletes Docker volumes.
- The Grafana reader initializer defaults to PostgreSQL's local Unix socket during `initdb`, while honoring
  explicit `POSTGRES_HOST` or standard `PGHOST` for operator-run onboarding.
- MQTT topic validation compares the complete expected topic, so isolated hierarchical namespaces remain strict
  without rejecting their slash-separated prefix.
- Grafana's provisioned PostgreSQL datasource consumes the environment-specific database name; dev, isolated
  staging, and E2E no longer silently query the production-default database name.
- Docker E2E accelerates evaluator intervals through a disposable file-provisioning overlay. It does not mutate
  production alert rules or file-provisioned resources through Grafana's runtime API.
- Independent review found and drove closure of six fail-open or evidence gaps: incomplete PASS counts,
  zero-duration RC gates, mutable/mismatched image references, deletion after unverified Compose shutdown,
  production mode depending on a newly updated env file, and SQL-only Grafana alert checks. Regression tests now
  bind each corrected behavior; Grafana scheduler state is polled after true no-data, healthy, firing, and recovery
  evaluations while direct SQL remains supplemental.

## Deviations from brief

- Docker runtime E2E is `NOT_RUN`: the local Docker engine pipe was unavailable. Compose rendering and isolation
  assertions passed, but runtime success is intentionally not inferred.
- Real Edge/Core staging, 24-hour soak, exact-bundle rehearsal, rollback, canary, and 24-hour production observation
  remain `NOT_RUN`; the required Edge artifacts, runtime authority, and production authorization were unavailable.
- Branch protection was not mutated. A maintainer must require the exact `docker-e2e` status after the workflow is
  merged. Epic #225 and qualification issue #260 remain open.

## Tests added

- Report schema/round-trip, duplicate IDs, count consistency, alert consistency, identity drift, required-scope,
  `NOT_RUN`, synthetic-evidence, future actuator, private-field, and private-path failure tests.
- Persistence acceptance/read-back, cross-transport duplicate, lost-ACK retry, observation ordering, freshness,
  malformed/legacy, privacy allowlist, and Grafana runtime-query assertions.
- Staging/production prefix acceptance and rejection through pure, HTTP telemetry, HTTP photo, and MQTT boundaries,
  plus static and rendered Compose isolation checks.

## Commands run and results

| Status | Command | Result/evidence |
| --- | --- | --- |
| PASS | `python -m pytest -p no:cacheprovider -q` | 479 passed, 3 skipped after all review- and CI-driven revisions. |
| PASS | `python -m tools.agent_task check tomato-247-release-qualification-225 quality` | Ruff lint/format and mypy passed; 231 files / 121 source files checked. |
| PASS | `python -m tools.agent_task check tomato-247-release-qualification-225 security` | Bandit found no issues; dependency audit found no known vulnerabilities. |
| PASS | `python -m tools.agent_task compose tomato-247-release-qualification-225 config --profile observability` | Task-owned Compose configuration validated. |
| PASS | `docker compose --env-file deploy/senior-pomidor-staging.env.example -f docker-compose.yml -f docker-compose.staging.yml --project-name senior-pomidor-staging --profile observability config --quiet` | Exact staging overlay rendered; only assigned loopback ports remained after merge. |
| PASS | `python -m tools.release_qualification system-invariants ...` then `validate --require-pass ...` | Generated and revalidated a bounded report for exact synthetic image identities. |
| PASS | `python -m tools.ai_context_docs` | Canonical context summaries current. |
| PASS | `git diff --check` | No whitespace errors; configured Windows line-ending warnings only. |
| NOT RUN | `RUN_DOCKER_E2E=1 python -m pytest -p no:cacheprovider -q tests/test_docker_e2e.py` | Local Docker engine unavailable; the final fail-safe probe stopped before data deletion or stack mutation because existing project state could not be verified. |
| NOT RUN | `actionlint .github/workflows/ci.yml .github/workflows/release-qualification.yml` | `actionlint` is not installed; workflow YAML/convention tests pass. |

## Compatibility checks

- Telemetry v1/v2, `health_summary_v1`, operator reliability, HTTP/MQTT ingestion, PostgreSQL models,
  State Estimator, public privacy allowlist, and Grafana provisioning are covered by fixtures and the full suite.
- The supported real window (previous supported Edge to new Core, and new Edge to rollback Core `v0.2.4`) is encoded
  in the report contract but remains unverified until #250 produces real PASS evidence.
- Production API/schema and database schema are unchanged. Deployment order remains Core first, one Edge canary,
  then broader Edge rollout only after the required observation gate.

## Safety impact

- No production access/write, deployment, secret read, external export, real GPIO/actuator action, database/volume
  deletion, Guardrails/Executor bypass, or direct LLM-to-actuator path occurred.
- Staging is fail-closed on identity crossover and binds only loopback ports. Example credentials and digests are
  conspicuously synthetic; operators must keep the real env file outside the repository.
- Rollback is application-only to the previous immutable image. PostgreSQL, Grafana, Ollama, evidence, and volumes
  are preserved.

## Known limitations

- #260 remains the authoritative release blocker: Docker runtime, real Edge/Core replay, cross-version evidence,
  Grafana runtime transitions, 24-hour staging soak, exact-bundle rollback, canary, and production observation have
  no PASS evidence in this run.
- GitHub branch protection cannot be made required by a workflow file and still needs a maintainer change.
- This repository cannot implement Edge prerequisites or prove sensor, network, storage-media, or physical outcomes.

## Documentation changes

- `docs/CONTRACTS.md` defines all three evidence contracts and privacy/semantic rules.
- `docs/STAGING.md` defines the persistent isolated environment and identity boundary.
- `docs/OPERATIONS.md` defines all five qualification gates, exact identity, soak, canary, abort, and rollback rules.
- `.ai/CURRENT_STATE.md` records the deployable staging overlay and qualification contracts without claiming runtime
  evidence.

## Manual verification steps

- `NOT_RUN`: complete every checklist item in #260 with exact immutable artifacts and attach sanitized PASS reports.
- `NOT_RUN`: configure branch protection to require `docker-e2e`, then prove the CI job on the candidate PR.
- `NOT_RUN`: run real Edge/Core staging and 24-hour soak with external export disabled; abort on any count,
  duplicate, health, alert, privacy, or bounded-resource mismatch.
- `NOT_RUN`: with separate authorization, rehearse application-only rollback and perform Core-first/one-Edge canary;
  retain backup/checksum and post-rollback health/read evidence. Keep #225 open until the final 24-hour gate passes.

## Final diff review

- Unrelated source changes were preserved. The diff was checked for production values, credentials, private paths,
  raw payload/reason leakage, non-loopback ports, external export, destructive cleanup, response/schema drift,
  synthetic PASS promotion, actuator claims, unbounded logs, and rollback gaps.
