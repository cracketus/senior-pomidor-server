# Tomato Brain Map R1 implementation specification

Status: topology-provider slice implemented; reader, evaluator, API, and UI runtime NOT_IMPLEMENTED.
Owner: Server. Baseline: 2026-09-09. Authorization: owner accepted the ADR baseline and delegated preimplementation refinement.
Authority: [accepted cross-system decisions](https://github.com/cracketus/senior-pomidor/blob/main/docs/architecture/tomato-brain-map/implementation-decisions.md).
Existing [contracts](CONTRACTS.md) remain authoritative for current endpoints. This document specifies additive future Map behavior.

Issue #332 implements only the isolated, read-only `app/map` topology boundary and sanitized
`config/topology/` history described below. It is packaged in the runtime image but is not imported by
FastAPI or application startup. It performs no database, network, estimator, control, export, or hardware
operation. Issues #333-#336 remain required before the rest of this specification exists at runtime.

## Outcome and boundaries

An operator inspects a bounded moisture-observation gap for synthetic targets A/B, distinguishes receipt from observation time, and opens the evidence behind each capability result.
Implement within FastAPI, with pure evaluation and separate read adapters. No new service, migrations, cache, materialization, control, estimator replay, live public route or graph editor in R1.
The Map describes observation availability, never plant health or permission to water.

## Inspected baseline

Server main 3bcbc15bc94b2eca1d45be8e3713c26d5b0b5c73:
- app/models.py: TelemetryEvent, PodReading and PodError carry raw evidence; received_at is an ingest proxy. SensorHealthSnapshot has no publication timestamp.
- app/services.py: ingest timestamp is assigned before commit; duplicate delivery does not establish a new observation.
- app/state_estimator/persistence.py and app/api.py: latest state can estimate and persist. Map MUST NOT invoke that path.
- app/state_estimator/adapters.py: absent soil fields and synthetic health metadata cannot establish fresh soil acquisition.
- config/state_estimator_v1.yaml: audited defaults support 600-second cadence and 1200-second freshness; actual deployed configuration is unverified.
The frozen [audit](https://github.com/cracketus/senior-pomidor/blob/main/docs/architecture/tomato-brain-map/implementation-audit.md) records limitations. No production inspection or test execution is implied.

## Contract and API

Proposed contract identifier: senior-pomidor.map.v1. Producer: Server; consumers: operator CLI/TUI and synthetic demonstration. Edge produces existing telemetry, not this projection.
Implement additive GET routes under /api/v1/map: /topology, /snapshot, /timeline and /evidence/{evidence_id}. All require explicit authorized entity scope; evidence dereference must recheck scope and query context. No arbitrary DB IDs, paths or SQL accepted.

| Input | Meaning |
| --- | --- |
| entity_id | Repeated opaque IDs, 1..50, no implicit all-devices scope |
| mode | AS_KNOWN_CORE default; RECONSTRUCTED alternative |
| at | UTC instant for topology/snapshot |
| from, to | UTC half-open timeline range; mutually exclusive with at |
| data_cutoff | One UTC request-start default, echoed; selected time/range cannot exceed it |
| cursor | Opaque continuation bound to the whole request |
| page_size | 1..500 intervals; default 500 |

Permit repeated entity_id for distinct IDs; reject duplicate IDs and repeated singleton arguments. Reject naive timestamps, unknown mode, conflicting query arguments and reversed/empty ranges. A timeline without bounds defaults to [cutoff-24h, cutoff); one missing bound is invalid. A snapshot without at defaults to cutoff. Maximum range 7 days.
Authorization precedes entity lookup, so denied scopes do not reveal entity existence. The private access boundary must be demonstrated before any non-isolated enablement.

| Response field | Required semantics |
| --- | --- |
| schema_version, evaluated_at | Version and UTC request clock; evaluation time is not publication evidence |
| scope, mode, data_cutoff | Resolved query, never silently broadened |
| versions | topology revision/digest, profile and adapter versions |
| coverage | Requested and examined bounds, missing evidence reasons |
| completeness | COMPLETE or PAGINATED; computation never silently uses truncated input |
| entities / intervals | Typed results; deterministic entity/time ordering |
| next_cursor | Nullable; pagination is presentation-only over complete bounded evaluation |
| evidence_refs | Bounded IDs/digests and typed provenance; no private raw errors |
| fidelity | Per-result INGEST_TIME_PROXY, GENERATION_TIME_PROXY, RECONSTRUCTED, UNKNOWN; EXACT only if actually supported |

Entity results keep implementation, deployment, operational, freshness and capability dimensions separate. Operational native enum is retained with source/version; no arbitrary global enum translation. Freshness: FRESH, STALE, UNKNOWN, NOT_APPLICABLE. Capability: AVAILABLE, UNAVAILABLE, DEGRADED, UNKNOWN, NOT_APPLICABLE.
Reason codes must distinguish NO_FRESH_VALID_OBSERVATION, INVALID_OBSERVATION, EXPLICIT_READ_FAILURE, MISSING_UPDATE, MISSING_BINDING, MISSING_CALIBRATION, CLOCK_INVALID, CONTRADICTORY_EVIDENCE, DISABLED and UNKNOWN_HISTORY.
Each assertion carries FACT, INFERENCE or UNKNOWN; hypotheses are deferred. A native DISCONNECTED report is a fact about the report.

Use existing error-envelope conventions, with stable machine code and request correlation:
400 invalid query/cursor; 403 denied; 404 unknown authorized entity; 409 SNAPSHOT_CHANGED; 422 QUERY_LIMIT_EXCEEDED; 429 busy; 503 TOPOLOGY_UNAVAILABLE/backend unavailable; 504 QUERY_TIMEOUT.
Missing history yields successful UNKNOWN. Backend failure never yields a fabricated outage interval.

## Topology and binding selection

`TopologyProvider` is implemented against strict `config/topology/` YAML. Each file contains one complete package revision with schema_version, revision_id, recorded_at, effective interval, provenance, entities, bindings, capability profiles, digest and optional supersedes.
Separate asset, source channel, target plant/container and deployment identities. Binding lookup uses the observation time, never current placement.
Validate safe YAML, duplicate keys/IDs, unknown fields/version, dangling references, invalid intervals, conflicting revisions and containment/capability cycles. Physical/data cycles are allowed.
Corrections are append-only revisions. AS_KNOWN_CORE uses revisions recorded by selected time; RECONSTRUCTED uses revisions recorded by cutoff. Within that bound select the explicit superseding correction applicable at effective time; ambiguous overlaps fail validation.
Retain the supported history in the deployed package. Atomically switch only after complete validation; bad reload retains the last valid revision and exposes a configuration error. Missing initial package returns 503.
Synthetic seed: one source, two channels, distinct targets A/B, explicit synthetic calibration provenance. No private IDs or inferred historical deployment dates.

## Evidence selection and evaluation algorithm

1. Capture request clock/cutoff and immutable topology/profile snapshot; authorize scope and validate budgets.
2. Read raw evidence in one READ ONLY REPEATABLE READ transaction. Set a 5-second statement timeout; cap aggregate input rows including lookback at 100,000 (+1 to detect overflow). Apply the cap across evidence types, not per table.
3. AS_KNOWN_CORE at T requires observation <= T and received_at <= T. RECONSTRUCTED requires observation <= T and received_at <= cutoff. Reject malformed/future-clock evidence as usable; show clock uncertainty without correcting timestamps.
4. Deduplicate by record_id or legacy source plus durable event ID. Sort by observation time, ingest time, durable identity. Preserve channel-level explicit errors and invalid values.
5. Seed each channel from the latest value, explicit error or disable evidence within its max-age window; never use the latest payload alone. Keep omitted updates separately. Example: soil at 10:00 plus air-only at 10:10 must seed the soil value for a range starting 10:15 and remain fresh through 10:20 inclusive. Include this cross-range regression. Then evaluate observation, arrival, expiry and topology transition boundaries. Older missing history stays UNKNOWN.
6. Validate mapped enabled numeric finite percentage 0..100 with explicit configured conversion/calibration provenance and source quality. ADC alone is not calibrated percent. Invalid or failed latest observation prevents substitution of an older green value. Omission alone keeps the previous value until expiry.
7. Evaluate each target independently. all_of unavailable dominates unknown; any_of needs one sufficient available branch. Explicit unresolved contradiction overrides a would-be available redundant result to UNKNOWN. No averaging or inferred equivalence.
8. Emit reasons, source evidence references, selected versions, fidelity and coverage. Source silence establishes absence of fresh Core observation, not physical failure.

Freshness age <= 1200 seconds is inclusive by accepted ADR. Canonical stored/evaluation precision for R1 is UTC microseconds; reject sub-microsecond query precision. Emit half-open freshness intervals ending at observation+max_age+1 microsecond, preserving point equality at the threshold. Clip to request end. Test exact threshold and both adjacent microseconds. This is a discrete-time encoding of the accepted rule, not extra grace time.

Late arrivals become eligible at receipt time in AS_KNOWN_CORE, but their age remains based on observation time. In reconstruction they may fill historical gaps. Selecting a historical policy without proof it was deployed must explicitly say reconstructed policy.

## Consistency and resource bounds

At most 2 concurrent Map evaluations per process; reject overload with 429. Bound normalized input and final serialization; 1 MiB response ceiling. Paginate intervals up to 500/page; if a single result cannot fit, return explicit limit error.
Cursor binds authorized scope, time/mode/cutoff, revisions, ordering boundary and SHA-256 normalized input digest. Opaque server-validated cursor cannot grant scope. Recompute bounded input on continuation; mutable input/version changes return 409 and require restart.
Canonical digest serialization must fix UTC microseconds, object key ordering, finite numeric representation and source identity/schema; publish golden vectors during implementation.
No cross-request database snapshot is claimed. Keep database transaction short; pure evaluation follows extraction. Capture all required rows in the same transaction.
Benchmark synthetic 7-day / 50-entity input near the row cap before expansion; record dataset, machine, row count, p50/p95, peak memory, timeouts and response sizes. Budgets are not measured SLOs.

## Acceptance and test ownership

The Topology row is implemented as synthetic software evidence by issue #332. All later rows remain future
implementation obligations and `NOT_RUN`.

| Slice | Required evidence | Scope scenario IDs |
| --- | --- | --- |
| Topology (implemented) | identity collision, replacement/relocation, late correction, bad reload/first startup, cycle classes | S06-S08, S11 |
| Reader | delayed receipt, two modes, dedup, late/out-of-order error, absent field, mixed channel freshness | S02-S05, S09, S14-S16 |
| Evaluator | two targets, disabled/missing mapping/calibration, numeric invalidity, contradiction, threshold ±1 microsecond | S01, S04-S05, S10-S12 |
| API | authorization, same scoped evidence drilldown, read-only DB and no estimator calls, all limit/error paths, changed cursor input | S13 plus TBM-R07-R10 |
| UI/demo | mode/fidelity prominent, backend vs unknown, missing/disabled state, bounded evidence card, sanitized reproducible walkthrough | S01-S16, TBM-R11-R12 |

Reference [scope scenarios](https://github.com/cracketus/senior-pomidor/blob/main/docs/architecture/tomato-brain-map/scope.md).
Reader tests must verify unchanged counts/content of canonical state, anomalies, simulations and telemetry after repeated requests. Use real isolated PostgreSQL transactions for read-only/isolation checks; mocks alone are insufficient.
Future coding tasks select context/checks from AGENTS.md and .ai/test-matrix.yaml based on actual changed paths. Typical classes: pure_software + schema_data_contract; edge compatibility/public contract overlays when relevant. Required commands include python -m pytest -q and nox -s lint format_check types, plus schema round-trip, old/current fixture replay and named-consumer checks. Security integration adds security and dependency checks. No hardware test is required for the pure synthetic evaluator.

## Rollout, rollback and readiness

Sequence: synthetic topology -> raw reader -> pure capability -> private bounded API -> existing operator UI integration -> synthetic acceptance.
Do not add routes to public ingress. Enable only in isolated development until authorization and resource behavior pass. Real bindings, calibration and historical coverage are UNVERIFIED and gate real-data claims.
Rollback disables/removes Map routes and returns to the prior application version; no migration or canonical data rewrite is planned. Abort on any canonical write, scope leak, unexpected external action or unbounded query.
Existing TUI/API work remains in server #204/#205/#207; Map adds a specialized projection, not a replacement operator framework. Edge #70/#71 and server #199 are future provenance/discovery integration, not prerequisites for synthetic R1.

## Owning backlog

- [[Tomato Brain Map][R1] Implement validated versioned topology provider](https://github.com/cracketus/senior-pomidor-server/issues/332)
- [[Tomato Brain Map][R1] Add bounded temporal raw-evidence reader](https://github.com/cracketus/senior-pomidor-server/issues/333)
- [[Tomato Brain Map][R1] Implement pure target capability and interval evaluation](https://github.com/cracketus/senior-pomidor-server/issues/334)
- [[Tomato Brain Map][R1] Expose scoped read-only API with bounded pagination](https://github.com/cracketus/senior-pomidor-server/issues/335)
- [[Tomato Brain Map][R1] Add operator timeline and evidence card to existing UI work](https://github.com/cracketus/senior-pomidor-server/issues/336)

Cross-repository acceptance: [umbrella #120](https://github.com/cracketus/senior-pomidor/issues/120), [Edge #150](https://github.com/cracketus/senior-pomidor-plant-v2/issues/150).
