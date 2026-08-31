# Implementation Report: Restore Edge/Core health compatibility

Issue/brief: [#283](https://github.com/cracketus/senior-pomidor-server/issues/283) / human-approved hotfix plan

Agent run ID / audit artifact: `20260831-issue-283-coder` /
`.ai/agent-runs/20260831-issue-283-coder.json`

Branch/worktree: `fix/283-edge-core-health-compatibility` / shared repository working copy

Task classes and risk flags: `pure_software`, `schema_data_contract`, `infrastructure_deployment`;
`edge_server_compatibility`, `production_availability`, `public_contract`.

Applicable `SP-FAIL-*` IDs: `SP-FAIL-001`--`004`, `SP-FAIL-009`, `SP-FAIL-011`, `SP-FAIL-014`,
`SP-FAIL-015`.

## Implemented behavior

- Preserves the additive `application.service_manager` discriminator and canonical health aggregate through
  tolerant HTTP/MQTT normalization and persistence.
- Evaluates explicit Docker process-only telemetry as healthy only for `service_manager=none` with a running
  process; missing, invalid, or contradictory evidence remains `UNKNOWN`.
- Retains the one-release complete legacy-systemd fallback and prevents malformed discriminators from entering it.
- Keeps component `ALERT` and `UNKNOWN` precedence over an otherwise healthy aggregate.
- Aligns Grafana dashboard and alert semantics, including the canonical aggregate critical rule.
- Keeps production promotion blocked on Edge
  [#142](https://github.com/cracketus/senior-pomidor-plant-v2/issues/142) acceptance and a real canary.

## Files changed and purpose

- `app/telemetry.py`, `app/edge_reliability.py`: normalization and deterministic evaluator behavior.
- `docs/schemas/telemetry-v2.schema.json`, `tests/fixtures/contracts/telemetry_v2.json`: additive producer
  discriminator/aggregate contract and canonical fixture.
- `docker/grafana/provisioning/alerting/edge-reliability-alerts.yml` and the Edge reliability dashboard JSON:
  bounded alert and display semantics.
- HTTP, MQTT, reliability, operator, schema, Grafana, Docker E2E, and release-asset tests: boundary and regression
  evidence.
- `docs/CONTRACTS.md`, `docs/PRODUCTION_RELEASE_INSTALLATION_RUNBOOK.md`: rollout, compatibility, canary, and
  rollback guidance.
- `.ai/agent-runs/20260830-*.json`, `.ai/agent-runs/20260831-*.json`: bounded implementation/review-fix audit.

## Design decisions

- The wire change stays additive in `senior-pomidor.edge.telemetry.v2`; no schema-version bump or migration is
  required.
- An invalid present discriminator is preserved internally as an invalid marker rather than treated as absent,
  preventing unsafe legacy fallback.
- Discriminator-absent legacy compatibility requires complete systemd evidence and remains temporary.
- Core rolls out first; Docker Edge then emits `service_manager=none`. Broader promotion waits for real canary
  evidence.

## Deviations from brief

- Real Docker E2E could not run locally because the Docker Desktop Linux engine was unavailable. The opt-in test
  remains part of required PR CI.
- Production, rehearsal, and Edge canary checks remain `NOT_RUN`; no authorization for those actions was given.

## Tests added

- Valid, missing, invalid, and contradictory discriminator cases across schema, HTTP, MQTT, evaluator, operator,
  and Grafana consumers.
- Canonical aggregate normalization, freshness, status mapping, component precedence, and critical alert behavior.
- Docker E2E assertions for discriminator/aggregate persistence and the five-rule Grafana inventory.
- Production-runbook regression coverage for verified rollback identity and optional canary handling.

## Commands run and results

| Status | Command | Result/evidence |
| --- | --- | --- |
| PASS | `python -m pytest -q` | 518 passed, 12 skipped. |
| PASS | `python -m pytest -q tests/test_edge_reliability.py tests/test_api.py tests/test_contract_fixtures.py tests/test_mqtt_worker.py tests/test_operator_edge_reliability.py tests/test_grafana_provisioning.py tests/test_release_assets.py tests/test_docker_e2e.py` | 163 passed, 1 skipped. |
| PASS | `python -m pytest -q tests/test_compose_config.py` | 11 passed. |
| PASS | `nox -s lint format_check types` | Ruff lint/format and mypy passed. |
| PASS | `python -m tools.agent_audit <changed-agent-run>` | All eight supporting artifacts passed after canonicalization. |
| NOT RUN | `RUN_DOCKER_E2E=1 python -m pytest -q tests/test_docker_e2e.py` | Docker Desktop Linux engine unavailable locally. |
| NOT RUN | Real staging/rehearsal/canary/production | Human-owned evidence; no deployment authorization. |

## Compatibility checks

- Producer schema, old/current fixtures, HTTP ingestion, MQTT ingestion, persisted readback, shared reliability
  evaluator, operator read model, Grafana provisioning, and Docker E2E assertions are covered.
- Edge producer implementation and physical staging remain outside this repository and are tracked by Edge #142.
- The discriminator-absent compatibility path remains for one release cycle.

## Safety impact

- No physical action, GPIO, actuator, Control, Guardrails, or Executor behavior changes.
- No database migration, destructive operation, secret access, external export, or production write occurred.
- Rollback is application-only to the previous immutable Core image while preserving PostgreSQL, shared services,
  volumes, and telemetry.

## Known limitations

- Local Docker E2E and real Edge/Core canary evidence are pending. Production promotion remains blocked.

## Documentation changes

- Contract semantics and rollout order are documented in `docs/CONTRACTS.md`.
- Production preflight, canary, Grafana verification, rollback identity, and execution log are documented in
  `docs/PRODUCTION_RELEASE_INSTALLATION_RUNBOOK.md`.
- Core RC evidence records Edge #142 as an explicit blocker in `docs/implementation-reports/ISSUE-260.md`.

## Manual verification steps

- `NOT_RUN`: execute the exact immutable Core/Edge staging pair, copied Edge replay, 24-hour soak, rollback
  rehearsal, and approved real canary. Abort on any `ALERT`, unexplained `UNKNOWN`, identity/count mismatch,
  duplicate, stale-to-healthy transition, or privacy/export violation.

## Final diff review

- Browser artifacts and the local CSV export are excluded from the commit.
- No secrets, private infrastructure, raw production data, debug artifacts, destructive operations, weakened
  validation, or unrelated source changes are included.
