# Implementation Report: Idempotent telemetry ingestion and ACK contract

Issue/brief: `cracketus/senior-pomidor-server#200`; human-approved Implementation Brief supplied in the task.

Branch/worktree: `feature/ISSUE-200-telemetry-ack` / `.agent-worktrees/issue-200-telemetry-ack`

Task classes and risk flags: `pure_software`, `schema_data_contract`, `infrastructure_deployment`,
`edge_hardware_integration`; `data_loss_migration`, `edge_server_compatibility`, `production_availability`,
`public_contract`.

Applicable `SP-FAIL-*` IDs: `SP-FAIL-004`, `SP-FAIL-005`, `SP-FAIL-006`, `SP-FAIL-011`.
`SP-FAIL-009`, `SP-FAIL-010`, `SP-FAIL-014`, and `SP-FAIL-015` were reviewed and are not behaviorally
applicable because state shape, units, packaging, and filesystem behavior did not change.

## Implemented behavior

- Migration `0009_telemetry_record_id` adds nullable globally unique `telemetry_events.record_id` while
  preserving historical rows and `uq_telemetry_event_identity`.
- Telemetry v2 accepts optional 1-128 character `record_id` values from `A-Za-z0-9_.:-`; invalid identifiers
  and malformed JSON return HTTP `400` without a correlation ACK.
- A committed first delivery returns exact HTTP `202` accepted ACK; identical replay returns exact HTTP `202`
  duplicate ACK. Same-ID content conflicts and observation-identity conflicts return bounded HTTP `200`
  rejected ACKs without overwriting the stored row.
- Valid correlated payload failures return `invalid_payload`; SQLAlchemy storage failures return HTTP `503`
  `storage_unavailable` without exception details. ACKs are constructed only after the persistence call commits.
- HTTP and MQTT share `record_id` persistence identity. Both transport orders preserve one event, while callers
  of the legacy `persist_telemetry` API still receive `TelemetryEvent`.
- Requests without `record_id` retain legacy identity deduplication and `accepted/event_id` responses for the
  compatibility window.
- Bounded key-value logs include outcome, source, record ID, and event ID where one exists, without payloads or
  database exception text.

## Files changed and purpose

- `migrations/versions/0009_telemetry_record_id.py`, `app/models.py`: additive nullable unique identity.
- `app/validation.py`: strict `record_id` boundary validation.
- `app/services.py`: outcome-aware persistence, replay detection, conflicts, concurrency recovery, and legacy
  wrapper.
- `app/api.py`, `app/mqtt_worker.py`: actionable ACKs, shared identity, safe failures, and structured logs.
- `docs/schemas/telemetry-v2.schema.json`, `tests/fixtures/contracts/telemetry_v2.json`,
  `tests/fixtures/edge_integration/telemetry_mqtt.json`: executable v2/spool contract.
- `tests/test_api.py`, `tests/test_telemetry_idempotency.py`, `tests/test_telemetry_migration.py`,
  `tests/test_contract_fixtures.py`, `tests/test_edge_integration_fixtures.py`, `tests/test_docker_e2e.py`:
  focused, concurrency, migration, boundary, fixture, transport, and PostgreSQL E2E
  coverage.
- `docs/CONTRACTS.md`, `docs/PI_INTEGRATION_RUNBOOK.md`, `docs/OPERATIONS.md`, `.ai/CURRENT_STATE.md`,
  `CHANGELOG.md`: contract, canary, rollout/abort/rollback, current-state, and release documentation.

## Design decisions

- Raw JSON object equality defines identical content; source transport is not payload content. This keeps the
  edge spool record immutable and makes MQTT/HTTP replay symmetric.
- Existing rows are resolved before insert and again after a uniqueness race. Database constraints remain the
  concurrency authority; the original event is never updated.
- `persist_telemetry_result` is the new outcome-aware extension point. `persist_telemetry` delegates to it and
  preserves existing caller types and behavior.
- Error codes are a fixed bounded set: `invalid_payload`, `record_id_conflict`,
  `observation_identity_conflict`, and `storage_unavailable`.

## Deviations from brief

- None in implementation. Docker/PostgreSQL E2E and human-operated rehearsal/canary evidence are pending because
  Docker was unavailable and no production, restore, or edge authority was granted.

## Tests added

- Exact accepted/duplicate/rejected/retry/legacy bodies, invalid identifiers, malformed JSON, authentication
  compatibility, lost-ACK replay, conflict immutability, and safe storage errors in `tests/test_api.py`.
- Independent-session concurrent identical submissions in `tests/test_telemetry_idempotency.py`.
- Populated pre-0009 upgrade preserving count, raw payload, timestamp, nullable column, unique index, and legacy
  constraint in `tests/test_telemetry_migration.py`.
- MQTT/HTTP ordering, v2 edge fixture, serialization round trip, and 500-record backlog plus replays in contract
  and edge-integration tests.
- PostgreSQL Docker E2E assertions for exact ACKs and `COUNT(*) = 1` were added but not executed locally.

## Commands run and results

| Status | Command | Result/evidence |
| --- | --- | --- |
| PASS | `python -m pytest -q tests/test_api.py tests/test_telemetry_idempotency.py tests/test_telemetry_migration.py tests/test_mqtt_worker.py tests/test_contract_fixtures.py tests/test_edge_integration_fixtures.py` | 61 passed before final review additions. |
| PASS | `python -m pytest -q` | 300 passed, 1 Docker-gated skip before two final contract assertions. |
| PASS | `python -m pytest -q -p no:cacheprovider --basetemp E:\MyProjects\senior-pomidor-server\.agent-tasks\issue-200-telemetry-ack\pytest-full-2` | Final revision: 302 passed, 1 skipped. Task-owned temp path avoided a host pytest-temp ACL failure. |
| PASS | `nox -s lint format_check types` | Ruff lint/format and mypy passed in clean nox environments. |
| PASS | `python -m tools.agent_task compose issue-200-telemetry-ack config` | Isolated Compose config validated; no containers started. |
| PASS | `python -m tools.ai_context_docs` | Generated context summaries remain current after the current-state update. |
| PASS | `git diff --check` | No whitespace errors. |
| PASS | contract/edge focused suites above | Schema bounds, JSON round trip, v1/v2 fixture replay, HTTP/MQTT consumers, retry path, and 500-record backlog passed. |
| NOT RUN | `$env:RUN_DOCKER_E2E='1'; python -m pytest -q tests/test_docker_e2e.py` | Docker Desktop Linux engine pipe was unavailable. |
| NOT RUN | isolated upgrade/restore against the candidate PostgreSQL bundle | Human-owned backup/restore rehearsal is not authorized; SQLite forward-migration preservation test passed. |
| NOT RUN | production/edge canary with `senior-pomidor-plant-v2#67` checker | Requires an authorized human and real edge spool. |

Two post-review pytest attempts failed before test execution because host and reused task pytest temp/cache paths
became ACL-inaccessible on Windows. A fresh verified task-owned path produced the final full PASS. A direct host
`mypy app tools tests` lacked `types-PyYAML`; the required clean `nox -s ... types` session installed declared dev
dependencies and passed.

## Compatibility checks

- Legacy v1/v2 fixtures and no-`record_id` HTTP behavior passed.
- Active v2 spool fixture, schema bounds, serialization, API persistence/read, MQTT-first/HTTP-first replay, and
  a 500-record mixed backlog passed.
- PostgreSQL Docker behavior and the external released edge sender remain unverified locally and are `NOT RUN`.
  The one-release-cycle compatibility window and rollout order are documented.

## Safety impact

- No production access, deployment, secrets, public export, GPIO, actuator, Guardrails, or Executor changes.
- The migration is additive and nullable. Application rollback retains the column/index and all telemetry; no
  downgrade or deletion is part of rollback.
- Logs and responses exclude payloads, database exception details, infrastructure identifiers, and secrets.

## Known limitations

- Docker/PostgreSQL E2E, candidate-bundle restore rehearsal, and real edge canary evidence remain `NOT RUN`.
- Legacy clients without `record_id` continue to rely on observation identity only and must migrate during the
  documented one-release-cycle window.

## Documentation changes

- `docs/CONTRACTS.md` owns the HTTP/MQTT identity and ACK contract.
- `docs/PI_INTEGRATION_RUNBOOK.md` owns the accepted/duplicate lost-ACK canary.
- `docs/OPERATIONS.md` owns backup-first rollout, abort boundaries, and application-only rollback.
- `.ai/CURRENT_STATE.md` and `CHANGELOG.md` record the deployable contract change.

## Manual verification steps

- `NOT RUN`: verify a checksummed backup, restore into an empty isolated target, run migration `0009`, compare
  historical counts/raw-payload hashes/timestamps, and verify readiness. Abort on any mismatch.
- `NOT RUN`: deploy application only after the additive migration, send one edge canary `record_id`, replay it,
  confirm exact accepted/duplicate ACKs and one row, then replay backlog in bounded groups. Abort on ACK mismatch,
  duplicates, or elevated retry/5xx results.
- `NOT RUN`: roll back only the application image while retaining the nullable column/index; confirm ingestion/read
  health and leave edge records spooled until the forward fix.

## Final diff review

- The original dirty `feature/TOMATO-AI-135-shared-context` checkout was untouched; all work is isolated on the
  issue branch/worktree.
- Reviewed for unrelated changes, payload/exception logging, secrets, debug artifacts, fixture drift, weakened
  validation, historical data mutation, and rollback gaps. None found.
