# Implementation Brief: #335 — Scoped read-only Tomato Brain Map API

Status: draft

Planner/version: Feature Planner 1.1

Approver/date: Human approval required

Issue/decision: GitHub #335; accepted Tomato Brain Map ADR baseline; authorization choice: mandatory bearer token plus server-side target allowlist.

Agent run ID / audit artifact: `20260909-issue-335-coder` / `.ai/agent-runs/20260909-issue-335-coder.json`

Execution model: `gpt-5.6-luna`

## Problem

The topology provider, PostgreSQL raw-evidence reader, and pure evaluator are packaged but have no runtime API. Operator clients cannot request bounded topology, snapshots, timelines, or evidence details.

Existing private/LAN GET routes do not provide entity-scoped authorization. The existing bearer helper is optional when a token is unset, so it cannot satisfy #335’s fail-closed boundary.

The reader also needs a mapping from topology sources/channels to PostgreSQL `device_id`, `pod_key`, and metric fields. That mapping is intentionally absent from the public topology contract and must not be guessed by the API.

## Desired outcome

Add four typed `senior-pomidor.map.v1` GET routes which require an authenticated explicit target scope, expose only bounded scoped data, support both Map modes, paginate complete results, provide scoped evidence drilldown, enforce all specified limits, remain read-only, and stay disabled outside isolated development.

## Current behavior and evidence

- `TopologyProvider` atomically loads immutable topology revisions and resolves point snapshots.
- `RawEvidenceReader` uses PostgreSQL `READ ONLY REPEATABLE READ`, a five-second statement timeout, a 100,000-row aggregate cap, and no State Estimator call.
- `evaluate_capabilities` emits deterministic intervals, reasons, fidelity, opaque evidence references, and a canonical digest.
- Focused Map baseline: 87 tests passed.
- PR #343 merged #334 into remote `main` at `7e547c7700dd07dd426d16d6515919e64a674bdd`; the local `origin/main` ref is stale and must be refreshed before task creation.
- Current checkout is clean but on `feature/TOMATO-334-map-capability-evaluator`.
- Existing operator reliability inherits a trusted-LAN boundary and has no application authorization or request-correlation infrastructure.
- No Map route or source-to-storage adapter configuration was found in inspected paths.

## Scope

- Add `/api/v1/map/topology`, `/snapshot`, `/timeline`, and `/evidence/{evidence_id}`.
- Add strict request/response/error models, JSON Schema, sanitized synthetic fixtures, and a versioned adapter configuration.
- Add fail-closed bearer authentication, target allowlisting, deterministic topology-range segmentation, single-transaction multi-segment evidence reads, evaluation orchestration, pagination, signed cursors, response-size enforcement, and scoped evidence resolution.
- Add bounded secret-safe logging, isolated configuration, tests, benchmark evidence, documentation, implementation report, and audit artifact.

## Out of scope

- Public/remote exposure, production activation, real IDs/bindings/calibration, caching, materialization, migrations, new services, unrestricted topology export, SQL/debug access, estimator replay, Control, hardware, UI work, and external actions.
- Changes to Edge, MQTT/HTTP ingestion, canonical State Estimator/Control, existing operator reliability, Grafana export, or public status contracts.
- Whole-season SLO or physical/root-cause claims.

## Architecture placement

- Add dedicated Map router, API models, auth/cursor helpers, adapter loader, and orchestration service under `app/map/`; register the router from `app/main.py`.
- Keep HTTP parsing/status mapping in the router. Keep topology selection, adapter resolution, read/evaluate/paginate/serialize behavior in Map services.
- Extend topology resolution for an atomic bounded range and raw reader for additive multi-segment reads in one read-only repeatable-read transaction.
- Add an internal point-query discriminator so snapshots evaluate the exact requested instant without moving `at` beyond `data_cutoff`.
- Never call `latest_state_or_estimate`, persistence, exporters, recovery, Control, or physical adapters.

## Affected contracts and consumers

- Additive private contract `senior-pomidor.map.v1`; producer: Map API/service; consumers: operator clients, #336 UI, synthetic demo.
- R1 `entity_id` means a target ID. Every route requires 1–50 distinct IDs; no implicit all-target scope.
- Settings: `MAP_API_ENABLED=false`, secret `MAP_API_TOKEN`, bounded JSON `MAP_API_ALLOWED_TARGET_IDS`, and `MAP_API_ADAPTER_CONFIG_PATH`.
- Map executes only when deployment mode is `development`, the flag is enabled, and token/allowlist/adapter config is valid. Other modes remain disabled.
- Adapter config uses `senior-pomidor.map.v1`, immutable adapter version/digest, strict source/channel-to-storage mappings, and a synthetic committed seed. Unknown fields, duplicates, dangling references, digest mismatch, and unit/profile mismatch fail closed. Storage IDs never appear in responses.
- Query rules: strict UTC microseconds; default `AS_KNOWN_CORE`; snapshot/topology `at=data_cutoff`; timeline default `[data_cutoff-24h,data_cutoff)`; max range 7 days; page size 1–500, default 500; reject duplicate IDs, repeated singleton args, one-sided ranges, unknown modes, malformed cursors, and mismatched continuation arguments.
- Responses include request ID, normalized scope/query, versions, coverage, fidelity, completeness, deterministic entities/intervals, evidence refs, digest, evidence context, and nullable next cursor.
- HMAC-signed bounded cursors bind scope, query, cutoff, versions, ordering boundary, page size, and normalized input digest. Cursors never authorize scope; bearer and target scope are rechecked every time.
- Error envelope: `{schema_version, request_id, error:{code,message}}`, with `X-Request-ID`. Map error codes map to 400/403/404/409/422/429/503/504 as specified in issue #335.
- Existing Edge, ingestion, storage, estimator/control, dashboards, export, public status, and operator reliability contracts are unaffected.

## Safety/risk classification

- Task classes: `pure_software`, `schema_data_contract`, `infrastructure_deployment`.
- Risk flags: `security_secrets`, `production_availability`.
- Applicable failures: `SP-FAIL-001`, `SP-FAIL-002`, `SP-FAIL-003`, `SP-FAIL-004`, `SP-FAIL-009`, `SP-FAIL-010`, `SP-FAIL-011`, `SP-FAIL-014`, `SP-FAIL-015`.
- Regression implications: explicit Compose defaults; existing API/worker health preserved; isolated loopback/synthetic credentials and no export; exact checkout/image recorded; versioned owned adapters; percent boundary tests and ADC rejection; real HTTP/PostgreSQL replay; Windows cleanup/path checks; explicit `app*` packaging.
- Production, real data/secrets, external export, hardware, and physical outcomes are `NOT_RUN`; isolated rehearsal evidence is maintainer-owned.

## Proposed implementation sequence

1. Refresh refs, verify `origin/main` contains merge `7e547c7`, run `python -m tools.agent_task preflight`, and create `feature/TOMATO-335-map-api` with task key `tomato-335-map-api`.
2. Rerun coder context routing for all actual paths with the three classes, both risk flags, and `--full`; record the pack and checks in the audit artifact.
3. Add strict Map models/schema/fixtures, adapter loader/configuration, safe defaults, and runtime packaging.
4. Add Map-only authentication, correlation IDs, strict request parsing, and authorization before entity lookup.
5. Add atomic topology range segmentation and one-transaction multi-segment evidence extraction with one aggregate row cap.
6. Add exact point snapshots, scoped topology closure, deterministic timeline composition, and sanitized evidence projection.
7. Add a non-blocking process-local semaphore of 2, stable error mapping, signed cursors/context, changed-input detection, and final serialized response ceiling of 1 MiB.
8. Add unit, contract, HTTP, concurrency, PostgreSQL no-write, Compose, and benchmark coverage; update docs/current state/report/audit.
9. Run every selected check, obtain independent review, and leave non-isolated activation evidence `NOT_RUN`.

## Failure modes

- Missing/invalid Map config: fail closed with bounded 503; existing API health/workers unaffected.
- Missing/wrong token or disallowed target: indistinguishable 403 without topology lookup.
- Allowed unknown target/evidence: bounded 404.
- Invalid query/cursor: 400; limits/oversized result: 422; third concurrent evaluation: immediate 429.
- PostgreSQL timeout: 504; other backend/topology failure: 503; missing history remains successful typed `UNKNOWN`.
- Cursor tamper/mismatch: 400; topology/adapter/evidence/order drift: 409 `SNAPSHOT_CHANGED`.
- Canonical write, estimator/external call, secret leak, public enablement, or unbounded work: abort and roll back.

## Backward compatibility

All changes are additive; no migration or durable-data rewrite. Map is disabled by default and hard-disabled outside development. Existing fixtures/contracts must replay unchanged. Cursor validity is limited to the API/token/input version; token rotation may invalidate cursors.

## Testing plan

Required commands:

- `python -m pytest -q tests/test_map_api.py tests/test_map_evaluator.py tests/test_map_reader.py tests/test_map_topology.py tests/test_contract_fixtures.py tests/test_api.py tests/test_compose_config.py tests/test_release_assets.py -p no:cacheprovider`
- `python -m pytest -q -p no:cacheprovider`
- `$env:RUN_DOCKER_E2E='1'; python -m pytest -q tests/test_docker_e2e.py -p no:cacheprovider`
- `nox -s lint format_check types`; `nox -s security`; `nox -s deps_audit`; `git diff --check`
- `python -m tools.agent_task compose tomato-335-map-api config`
- `python -m tools.validate_change --base origin/main --task-key tomato-335-map-api --explain --force full`
- `python -m tools.agent_audit .ai/agent-runs/20260909-issue-335-coder.json`

Required scenarios cover all issue acceptance paths: auth/scope leaks, both modes/cutoffs, exact point and 24h/7d ranges, limits, pagination/1 MiB, all error statuses, concurrency, cursor tamper/mutation, topology/adapter versions, fidelity/coverage/completeness/reasons/evidence round-trip, PostgreSQL read-only/no-write behavior, private-field exclusion, and Windows/Linux cleanup.

Benchmark five synthetic seven-day/50-target evaluations near 100,000 rows; record exact environment, rows, p50/p95, client peak memory, response/page sizes, page count, errors, and timeouts without asserting an SLO.

Manual: independent review and maintainer-owned isolated enable/read/disable rollback. Production, staging activation, real data/calibration, hardware, public exposure, and UI remain `NOT_RUN`.

## Observability

Log bounded route, request ID, mode, entity/row/interval counts, elapsed time, response bytes, result code, and version/digest identifiers. Never log tokens, cursors, target/storage IDs, payloads, raw errors, paths, SQL, or exception text. A successful log proves only bounded software completion, not physical availability.

## Documentation updates

Update `docs/TOMATO_BRAIN_MAP_R1_SPEC.md`, `docs/CONTRACTS.md`, `docs/OPERATIONS.md`, `.ai/CURRENT_STATE.md`, environment examples, runtime packaging docs, JSON Schema/fixtures, `docs/implementation-reports/ISSUE-335.md`, and the bounded `agent_run_v1` artifact. Mark API implemented but default-disabled/development-only; UI and real-data activation remain future work.

## Rollout and rollback

Use only an isolated task with loopback ports, synthetic credentials, external export disabled, and no real devices. Abort on scope leak, canonical write, estimator/external call, unbounded query/response, secret leak, existing endpoint regression, or unhealthy existing services. Disable `MAP_API_ENABLED` and revert the additive Map commit/application image; preserve PostgreSQL, telemetry, Edge spool, topology history, and shared platform services. Verify health/readiness, ingestion, existing reads, representative counts/hashes, and Map absence after rollback.

## Acceptance criteria

- [ ] Four typed routes and stable error envelopes implement the additive private Map contract.
- [ ] Every route requires valid bearer auth and explicit allowlisted target scope; denied IDs reveal no existence.
- [ ] Real HTTP → adapter → PostgreSQL read-only reader → evaluator → serializer/evidence flow is covered with no canonical writes or external actions.
- [ ] Mode, cutoff, versions, fidelity, coverage, completeness, reasons, evidence, digest, and correlation round-trip through schemas/fixtures.
- [ ] Limits are enforced: 7 days, 50 targets, 100,000 rows, 500 intervals/page, two concurrent evaluations, five-second DB timeout, 1 MiB response.
- [ ] Signed cursor/context binds scope/query/cutoff/versions/order/input digest; tamper cannot broaden scope; changed input returns `SNAPSHOT_CHANGED`.
- [ ] Missing history is typed `UNKNOWN`; backend failures are never empty/green success.
- [ ] Synthetic benchmark records dataset/environment/rows/latency/memory/pages/errors/timeouts with no unsupported SLO.
- [ ] Existing contracts and fixtures pass unchanged; Map is disabled by default and outside development.
- [ ] All matrix checks are recorded as `PASS`, `FAIL`, or `NOT_RUN`, followed by independent review.

## Blocking open questions

None. Bearer-token plus target-allowlist auth and clean post-#334 base were confirmed. Remote #334 is merged; executor must refresh stale local refs before creating the isolated task.

## Evidence and references

- `.ai/CORE_INVARIANTS.md`, routed full planner context, `.ai/test-matrix.yaml`, and full selected `SP-FAIL-*` records.
- GitHub #335, #205, #90, and merged PR #343 at `7e547c7700dd07dd426d16d6515919e64a674bdd`.
- Accepted Tomato Brain Map ADR decisions, scope S01–S16, TBM-R07–R10, and implementation audit.
- `docs/TOMATO_BRAIN_MAP_R1_SPEC.md`, `docs/CONTRACTS.md`, `docs/OPERATIONS.md`.
- `app/map/`, `app/api.py`, `app/config.py`, `app/main.py`, Compose/runtime packaging, and existing Map/API/contract/Docker tests.
- Unverified/excluded: production topology/configuration, private identities, real bindings/calibration, production coverage/performance, UI behavior, and physical outcomes.

Approval of this brief does not authorize production deployment, production data/secrets access, external export, or real hardware activation.
