# Implementation Brief

Status: approved

Planner/version: Codex Feature Planner, 2026-08-10

Approver/date: Human approval received in chat, 2026-08-10

Issue/decision: [#132](https://github.com/cracketus/senior-pomidor-server/issues/132)

## Problem

The server exposes separate health, readiness, worker-health, telemetry, and sensor-health
signals, but no bounded machine-readable summary for an operator or observability consumer.
Issue #132 requires a low-risk pilot that composes existing signals without changing recovery,
Control, Guardrails, Executor, actuator, deployment, or export behavior.

## Desired outcome

Expose one versioned, read-only health-summary response that reports an overall status, bounded
component statuses, reasons, and freshness for the selected server/node scope. Missing, stale, or
unavailable inputs must be represented as `UNKNOWN` or `WARN`; they must never produce a healthy
summary by default.

## Current behavior and evidence

- `app/main.py` exposes `GET /health` with only `{\"status\": \"ok\"}` and `GET /ready` with
  database/migration readiness.
- `app/readiness.py` checks database connectivity and Alembic revision equality.
- `app/worker_health.py` writes a UTC timestamped JSON health record; `app/worker_healthcheck.py`
  treats only configured healthy statuses no older than 90 seconds as healthy.
- `app/models.py`, `app/api.py`, and `app/state_estimator/` provide persisted telemetry,
  system-health, and sensor-health data that can be read without a migration.
- `docs/CONTRACTS.md` documents the existing `/health`, `/ready`, telemetry, and sensor-health
  surfaces; no unified health-summary contract was found in inspected paths.
- Issue #132 explicitly requires stale/missing data handling, no physical/deployment/secret/export
  side effects, selected test-matrix checks, and a workflow retrospective.

## Scope

- Add a read-only server-owned health-summary composition layer and HTTP endpoint
  `GET /health/summary`.
- Return a versioned `health_summary_v1` object containing `schema_version`, `status`,
  `generated_at` (UTC), `components`, `reasons`, and `data_freshness`.
- Compose only existing signals: API process availability, `/ready` database/migration state,
  worker-health freshness/status, and latest persisted telemetry/sensor-health freshness when a
  node is selected.
- Define deterministic status precedence: `ALERT` for explicit failed/critical required signals,
  `WARN` for degraded or stale-but-actionable signals, `UNKNOWN` for absent/unavailable required
  evidence, and `OK` only when required evidence is current and healthy.
- Bound component names, reason text, timestamps, and returned collections; omit secrets, paths,
  hostnames, IP addresses, raw telemetry, logs, and private payloads.
- Add focused unit/API failure-path tests and update the authoritative contract/operations
  documentation with examples and freshness semantics.

## Out of scope

- Automatic restart, remediation, recovery, retry, or alert delivery.
- Any change to Control, Guardrails, Executor, actuator, GPIO, or hardware behavior.
- New monitoring infrastructure, database tables, migrations, background jobs, or durable state.
- Changes to existing `/health`, `/ready`, telemetry, MQTT, or sensor-health response contracts.
- Public/exported status publication, Grafana Cloud changes, production deployment, or production
  data/secrets access.
- Inventing server-disk metrics when no existing bounded signal is available.

## Architecture placement

- The composition/read surface belongs in the server HTTP/read layer (`app/main.py` or a focused
  health-summary module), using existing readiness, worker-health, and persisted read APIs.
- It must not move State Estimator ownership, forecast/control logic, recovery behavior, or adapter
  responsibilities into the summary.
- The endpoint is observational only and must not mutate canonical storage or trigger external I/O
  beyond bounded local reads already required for the existing health surfaces.

## Affected contracts and consumers

- Artifact: new `health_summary_v1` HTTP response; producer is the server health-summary layer.
  `generated_at` and all interchange timestamps are UTC ISO-8601. Freshness values are named
  `age_seconds` and non-negative. Status is one of `OK`, `WARN`, `ALERT`, `UNKNOWN`.
- `node_id` is optional; absent node scope summarizes server-level signals only. Node-scoped
  telemetry/sensor freshness is included only when explicitly requested.
- Edge/MQTT: unaffected with evidence; no ingestion or edge contract changes.
- HTTP/API: affected; new endpoint and documented response contract.
- Storage/migrations: unaffected with evidence; read-only existing tables/files only.
- Fixtures: affected; add synthetic response/input fixtures if the contract is externalized.
- State Estimator/Control: unaffected with evidence; estimator output is read, never changed or
  used to authorize an action.
- Dashboards: unaffected unless a later approved issue adds a consumer; no dashboard wiring is in
  this pilot.
- Export/public dataset: unaffected with evidence; no export or publication path is enabled.
- Operations docs: affected; document endpoint, status semantics, safe degraded behavior, and
  rollback.

## Safety/risk classification

- Task classes from `TEST_MATRIX.md`: `pure_software`, `schema_data_contract`.
- Risk flags: `public_contract` is not selected unless the endpoint is intentionally exposed as a
  public status artifact; current proposal is an internal server API.
- Applicable `SP-FAIL-*` IDs:
  - `SP-FAIL-009`: test the nested versioned response shape against named consumers so summary
    fields are not silently flattened or reinterpreted.
  - `SP-FAIL-011`: exercise the response through the real FastAPI route, not only a validator or
    serializer unit test.
  - `SP-FAIL-014`: use UTC-aware timestamps and temporary health files with Windows-safe cleanup.
- Safety/production/physical boundaries: no physical or production evidence is required; manual
  deployment and hardware evidence remain `NOT_RUN`. Human review owns final scope approval.

## Proposed implementation sequence

1. Human approves this brief and resolves the blocking endpoint/scope questions.
2. Add a small pure composition module with explicit input models, thresholds, status precedence,
   UTC clock injection, and bounded secret-safe output.
3. Add the read-only route and preserve existing `/health` and `/ready` behavior.
4. Add happy-path and failure-path tests for current, missing, stale, malformed, and unavailable
   signals, including deterministic clock and temporary-file cases.
5. Update `docs/CONTRACTS.md` and `docs/OPERATIONS.md` with the version, fields, freshness rules,
   examples, and non-remediation semantics.
6. Run the selected matrix checks, inspect the diff for contract drift/secrets, and hand off for
   independent review.

## Failure modes

| Failure | Detection | Safe behavior | Test/fault injection |
| --- | --- | --- | --- |
| Database unavailable | readiness/read exception | `UNKNOWN` or `ALERT` per approved precedence; no raw exception/details | monkeypatched DB failure through route |
| Worker file absent, malformed, stopped, or stale | worker-health read/check | `UNKNOWN`/`WARN`; never `OK` | missing, invalid JSON, old UTC timestamp, stopped status |
| No node telemetry/sensor snapshot | empty query result | node component `UNKNOWN` with freshness reason | empty database fixture |
| Stale telemetry/sensor data | age exceeds documented threshold | `WARN` or `ALERT` per approved threshold | deterministic old timestamps |
| Malformed/unexpected persisted health shape | bounded parser rejects shape | component `UNKNOWN`; no raw payload in response | malformed synthetic JSON |
| Clock/timestamp error | invalid or future timestamp | `UNKNOWN`; bounded reason only | invalid and future timestamps |

## Backward compatibility

The change is additive: existing endpoints, telemetry schemas, MQTT topics, stored data, and worker
health files remain unchanged. `health_summary_v1` is a new response version; unknown future fields
must be ignored by consumers where practical. No migration or mixed-version data rollout is needed.
Rollback is removal/disablement of the new route and documentation; existing health/readiness
surfaces remain available.

## Testing plan

- Required focused checks: route-level tests for `OK`, `WARN`, `ALERT`, `UNKNOWN`, missing/stale
  telemetry, worker failures, readiness failure, malformed data, future timestamps, bounded output,
  UTC serialization, and no mutation.
- Required matrix checks for `pure_software`: `full_pytest`, `quality`, `diff_check`.
- Required matrix checks for `schema_data_contract`: `full_pytest`, `quality`, `diff_check`,
  `schema_validation`, `serialization_round_trip`, `fixture_replay`, `named_consumers`.
- Required commands after implementation: `python -m pytest -q`, `nox -s lint format_check types`,
  `git diff --check`.
- Required contract evidence: real FastAPI route tests plus old/current fixture serialization and
  named-consumer checks; no production or hardware checks.
- Feature Planner and Reviewer evaluations are required because this task exercises the agent
  workflow itself.
- Manual evidence: workflow retrospective and human review are required; deployment, physical, and
  production checks are `NOT_RUN`.

## Observability

The endpoint itself is the bounded signal. Logs, if needed, contain only component identifiers,
status, exception class, and bounded reason codes; never raw payloads, secrets, paths, host details,
or prompts. `generated_at` and each component `age_seconds` make freshness auditable. The summary
must not claim physical-world health or successful recovery.

## Documentation updates

- `docs/CONTRACTS.md`: endpoint, schema, fields, enum values, UTC/time/freshness semantics,
  optionality, and safe degraded behavior.
- `docs/OPERATIONS.md`: read-only usage, interpretation, and rollback/absence behavior.
- Workflow deliverables outside this brief: Implementation Report, independent Review Report,
  human review notes, and retrospective with measured timings and harness corrections.

## Rollout and rollback

Rollout is local/test-only first, with the route internal-only and disabled from any public/export path. Abort if the
route mutates storage, exposes sensitive fields, changes existing health/readiness responses, or
cannot distinguish missing/stale data from healthy data. Rollback removes the additive route and
docs; verify existing `/health`, `/ready`, telemetry, and MQTT behavior remains unchanged. No
production deployment or physical verification is authorized by this brief.

## Acceptance criteria

- [ ] Human approves this brief and the exact endpoint/scope decisions below.
- [ ] A versioned read-only `health_summary_v1` response is available through the approved route,
      with deterministic status precedence, UTC timestamps, bounded components/reasons, and
      freshness data.
- [ ] Current healthy synthetic inputs produce `OK`; missing, stale, malformed, unavailable, and
      critical inputs produce the approved non-healthy statuses with safe reason codes.
- [ ] Existing `/health`, `/ready`, telemetry, MQTT, storage, State Estimator, Control, Guardrails,
      Executor, and actuator behavior remains unchanged.
- [ ] No secrets, private network details, raw payloads, recovery commands, external exports,
      production writes, or physical side effects are introduced.
- [ ] Selected automated checks pass and every required manual item is recorded as `PASS`, `FAIL`,
      or `NOT_RUN`.
- [ ] Implementation Report, independent Review Report, human review notes, and workflow
      retrospective are produced for the pilot.

## Blocking open questions

None. Approved decisions: `GET /health/summary`; optional `node_id`; worker freshness of 90 seconds;
telemetry freshness of 20 minutes; internal-only response with no public/export consumer.

## Evidence and references

- Issue #132: pilot Planner–Coder–Reviewer workflow and health-summary acceptance criteria.
- `.ai/CORE_INVARIANTS.md`, `.ai/context-manifest.yaml`, `.ai/agents/feature-planner.md`,
  `.ai/agents/coding-agent.md`, `.ai/templates/implementation-brief.md`.
- `.ai/workflows/feature.md`, `.ai/TEST_MATRIX.md`, `.ai/test-matrix.yaml`,
  `.ai/KNOWN_FAILURES.md`.
- `app/main.py`, `app/readiness.py`, `app/worker_health.py`, `app/worker_healthcheck.py`,
  `app/api.py`, `app/models.py`, `app/state_estimator/`, `tests/test_api.py`,
  `tests/test_mqtt_worker.py`, `docs/CONTRACTS.md`, and `docs/OPERATIONS.md`.
- Approved assumptions to verify in implementation: no existing external consumer depends on an
  unimplemented endpoint, and the 20-minute telemetry threshold is a pilot-level summary threshold,
  not a change to existing alerting semantics.

Approval of this brief does not authorize production deployment, production data/secrets access,
or real hardware activation.
