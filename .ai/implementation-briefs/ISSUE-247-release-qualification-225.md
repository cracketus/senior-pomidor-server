# Implementation Brief: RC qualification for epic #225

Status: approved

Planner/version: human-provided release qualification plan / v1

Approver/date: user / 2026-08-26

Issue/decision: umbrella #247; release candidate `c71d019`; qualification of epic #225

Agent run ID / audit artifact: `20260826-issue-247-coder` /
`.ai/agent-runs/20260826-issue-247-coder.json`

## Problem

Epic #225 is functionally implemented, but the candidate lacks the mandatory system, Docker, cross-version,
Grafana-runtime, staging, rehearsal, canary, and rollback evidence required by the release policy. Existing
unit and provisioning tests cannot establish the real transport, persistence, or cross-repository paths.

## Desired outcome

The repository provides a required PR Docker E2E gate, strict machine-readable qualification artifacts,
deterministic system-invariant evidence, and RC evidence gates which fail closed on missing or `NOT_RUN`
required scenarios. The tools never infer real Edge, staging, canary, or production success.

## Current behavior and evidence

- Candidate `c71d019` contains #226-#229 and the four provisioned reliability alert rules.
- `tests/test_docker_e2e.py` is opt-in, uses a fixed project/ports, checks only HTTP duplicate delivery, does
  not exercise MQTT or reliability consumers, and calls `down -v`.
- `.github/workflows/ci.yml` has no separately named `docker-e2e` job.
- No versioned system-invariants, Edge/Core compatibility, or release-validation report contract exists.
- Live Edge, staging, canary, and production state are Unknown and unavailable to this coding task.

## Scope

- Add report contracts `senior-pomidor.system-invariants.v1`,
  `senior-pomidor.edge-core-compatibility-report.v1`, and `senior-pomidor.release-validation.v1` with strict
  UTC identity, counts, scenario, alert-outcome, and `PASS|FAIL|NOT_RUN` semantics.
- Add a bounded validator/generator and sanitized fixtures with semantic fail-closed validation.
- Add the required PR `docker-e2e` job and expand Docker E2E across readiness/migrations, HTTP/MQTT
  idempotency, persistence, latest/history, health summary, operator API, Grafana dashboards/rules, runtime
  alert SQL transitions, bounded failure logs, and task-owned cleanup with external export disabled.
- Add manually dispatched RC gates named `system-invariants`, `edge-core-e2e`, and `release-validation`.
- Add the server-side #202 staging boundary: an explicit observable deployment mode, staging-only device
  identity enforcement, and a persistent isolated Compose overlay with separate credentials, MQTT namespace,
  database, loopback ports, data paths, and external export disabled.
- Document evidence creation, prerequisites, staging isolation, exact-bundle, soak, canary, abort, and rollback.

## Out of scope

- Production deployment/writes, production secrets or paths, destructive database/volume operations, real
  GPIO/actuators, external export, and claims of physical-world validation.
- Edge repository implementation and its issues #69/#98/#100/#103/#104; the server only validates sanitized
  evidence produced by the approved real Edge workflow.
- #251 property testing, #91 performance, #96 fuzzing, #203 staging API, full #95 recovery, #47 notifications,
  #187 host observability, DSPy/VLM, and Season 2 work.
- Production API, telemetry, storage, health, or operator contract changes. The deployment mode is observable
  through rendered Compose/container labels without changing a production HTTP response.

## Architecture placement

- CI/workflow ownership: `.github/workflows/` and isolated Docker E2E under `tests/`.
- Environment-boundary ownership: `app/environment_boundary.py`, settings, HTTP/MQTT ingress, and the isolated
  `docker-compose.staging.yml` overlay. It cannot select production data or credentials by default.
- Evidence-contract ownership: `docs/schemas/`, fixtures, and `tools/release_qualification.py`.
- Existing API/MQTT/storage/State Estimator/Grafana owners are exercised without responsibility changes.
- Actuator invariants are explicitly `NOT_IMPLEMENTED`; no Control/Guardrails/Executor behavior is added.

## Affected contracts and consumers

- Three new report contracts are internal release artifacts. Producer: CI or an approved staging/operator
  workflow. Consumers: RC workflow, reviewer, release owner, and epic #225 evidence record.
- All report timestamps are UTC `Z`; SHAs are 40 lowercase hex characters; image identity is an immutable
  digest; counts are non-negative integers; report status is `PASS|FAIL|NOT_RUN`.
- Telemetry v1/v2, HTTP/MQTT, PostgreSQL, latest/history, `health_summary_v1`, operator reliability, State
  Estimator, Grafana provisioning, and public-export privacy are exercised but unchanged.
- The real Edge producer remains external and is not inferred from server fixtures.

## Safety/risk classification

- Task classes: `pure_software`, `schema_data_contract`, `infrastructure_deployment`,
  `edge_hardware_integration`.
- Risk flags: `security_secrets`, `edge_server_compatibility`, `production_availability`, `public_contract`.
- Applicable failures: `SP-FAIL-001`, `SP-FAIL-002`, `SP-FAIL-003`, `SP-FAIL-004`, `SP-FAIL-009`,
  `SP-FAIL-010`, `SP-FAIL-011`, `SP-FAIL-014`, `SP-FAIL-015`.
- Manual evidence owner: human release operator with approved staging/Edge/production access. Automation keeps
  unavailable evidence `NOT_RUN` and never activates hardware or export.

## Proposed implementation sequence

1. Add schemas, semantic validation, fixtures, and failure-path tests.
2. Expand isolated Docker E2E and make its separate job mandatory on pull requests.
3. Add the #202 server staging boundary and persistent isolated Compose overlay.
4. Add RC evidence workflow jobs and artifact upload.
5. Document the exact gates, isolation, abort/rollback, and evidence limitations.
6. Run every routed automated check; record manual gates without claiming success.

## Failure modes

- Missing/invalid identity, scenario, count, alert result, or required evidence: schema/semantic validator fails.
- `NOT_RUN` or `FAIL` in an RC-required scenario: the matching RC job fails closed.
- Compose interpolation, wrong image, non-loopback target, or enabled export: config/E2E assertion fails before
  qualification.
- Service/readiness/migration/worker failure: bounded service state and tail logs are emitted; cleanup targets
  only the verified disposable project/data root.
- Duplicate/lost-ACK behavior creates a second row: Docker gate fails on persisted count.
- Missing/stale/future/unknown becomes healthy: invariant tests and report generation fail.
- Grafana rule/query error or absent transition: Docker gate fails; no notification is sent.
- A staging identity presented to production, or a non-staging identity presented to staging, is rejected before
  persistence; development/rehearsal retain the current compatibility behavior.

## Backward compatibility

- Production contracts and database schema are unchanged.
- Supported window: existing telemetry v1/v2 fixtures and current Edge candidate to new Core; new Edge to
  `v0.2.4` is recorded only by real compatibility evidence.
- Core rolls out before one Edge canary. Legacy payloads remain supported for their documented one-release
  window. Rollback is application-only and preserves PostgreSQL/Grafana/Ollama.

## Testing plan

- Required: focused report/Docker/workflow tests; `python -m pytest -q`; `nox -s lint format_check types`;
  `nox -s security`; `nox -s deps_audit`; `git diff --check`; schema validation; serialization round-trip;
  v1/v2 fixture replay; named API/MQTT/storage/Grafana consumers; disconnect/retry paths; exact isolated
  Compose config; opt-in Docker E2E.
- Manual: real Edge cross-repository staging and 24-hour soak, exact-bundle rehearsal, rollback, one Edge
  canary, 60-minute/two-window observation, and 24-hour production telemetry. All begin `NOT_RUN`.

## Observability

- JSON reports contain bounded scenario IDs/statuses, UTC timestamps, identities, counts, fixed alert outcomes,
  and sanitized notes only. They exclude secrets, paths, service names, network identifiers, boot IDs, raw
  payloads, and logs.
- Docker failures retain only bounded Compose state and log tails in CI output/artifacts.

## Documentation updates

- `docs/CONTRACTS.md`, `docs/OPERATIONS.md`, schema fixtures, implementation report, and bounded audit record.
- `.ai/CURRENT_STATE.md` changes only if the deployable tooling facts change.

## Rollout and rollback

- Merge is human-only after the new PR gate is green. RC workflows run from exact SHA/digest identities.
- Abort on any required `FAIL|NOT_RUN`, readiness/worker/ingestion/count/duplicate/privacy/export/alert mismatch.
- Revert the qualification tooling/workflow patch for software rollback. Runtime release rollback stops only the
  application and restores the previous immutable image; it preserves shared data/services and rechecks health
  and reads. No destructive cleanup is permitted.

## Acceptance criteria

- [ ] `docker-e2e` is a separate required PR job and exercises the named end-to-end consumers and failures.
- [ ] All three strict report schemas have valid fixtures, round-trip tests, and negative semantic tests.
- [ ] `system-invariants` deterministically proves applicable current invariants and labels actuator invariants
  `NOT_IMPLEMENTED`.
- [ ] `edge-core-e2e` and `release-validation` fail closed unless real required scenarios are `PASS`.
- [ ] Grafana provisioning and four synthetic non-firing/firing/recovery query transitions run in Docker E2E.
- [ ] Operations docs preserve isolation, disabled export, exact identities, 24-hour soak, canary, abort, and
  application-only rollback boundaries.
- [ ] The #202 server staging overlay and ingress boundary prevent staging/production identity mixing and expose
  the active mode without using production paths, credentials, or external export.
- [ ] Routed automated checks are recorded; manual/physical/production evidence is not inferred.

## Blocking open questions

- P0 qualification child #260 was created and linked from #247; stale #228/#229 checkboxes in #225 were corrected.
- Edge repository/runtime artifacts and staging/production authority are unavailable; their gates remain manual
  and cannot be completed by this coding task.

## Evidence and references

- User-approved release qualification plan; issues #225, #247, #246, #202, #248-#252 and server #98.
- `.ai/CORE_INVARIANTS.md`, `.ai/context-manifest.yaml`, `.ai/test-matrix.yaml`, selected `SP-FAIL-*` records.
- Candidate `c71d019`; `tests/test_docker_e2e.py`; `.github/workflows/ci.yml`; Grafana provisioning files.

Approval of this brief does not itself authorize production deployment, production data/secrets access, or real hardware activation.
