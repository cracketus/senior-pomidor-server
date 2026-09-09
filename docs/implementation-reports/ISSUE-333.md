# Implementation Report: Bounded temporal raw-evidence reader

Issue/brief: [#333](https://github.com/cracketus/senior-pomidor-server/issues/333) / human-approved
Implementation Brief supplied in the implementation request

Agent run ID / audit artifact: `20260909-issue-333-coder` /
`.ai/agent-runs/20260909-issue-333-coder.json`

Branch/worktree: `feature/TOMATO-333-bounded-temporal-raw-evidence-reader` /
`.agent-worktrees/tomato-333-bounded-temporal-raw-evidence-reader`

Task classes and risk flags: `pure_software`, `schema_data_contract`; no risk flags.

Applicable `SP-FAIL-*` IDs: `SP-FAIL-009`, `SP-FAIL-010`, `SP-FAIL-011`, `SP-FAIL-014`,
`SP-FAIL-015`.

## Implemented behavior

- Adds immutable request, selector, evidence, health-fact, result, fidelity, validity, reason, and error-code
  models under `senior-pomidor.map.v1`. Requests require explicit channel/device/source scope, UTC
  microsecond timestamps, half-open windows of at most seven days, at most 50 sources, unique selectors,
  topology digest/revision, profile identity, effective interval, freshness, unit, and range.
- Adds one fixed PostgreSQL `UNION ALL` extraction across `TelemetryEvent`, selected `PodReading`, and
  selected `PodError` rows. It applies a single aggregate `LIMIT 100001`, fails rather than truncates, and
  never selects raw payload JSON.
- Opens exactly one transaction before reads, sets and verifies `REPEATABLE READ`, `READ ONLY`, and local
  `statement_timeout=5s`, captures all rows, rolls the read transaction back, and only then normalizes.
  SQLSTATE `57014`, overflow, unsupported dialect, and other backend failures have bounded typed codes.
- `AS_KNOWN_CORE` bounds receipt by the window end; `RECONSTRUCTED` bounds receipt by the resolved cutoff.
  Both retain original observation/receipt times and surface received future-clock evidence as unusable.
- Preserves source receipts (including omission evidence), valid/invalid values, explicit errors, disabled
  channels, and the latest relevant per-channel pre-window invalidating or value seed. Each seed respects
  that channel's own max age and effective binding interval; omission never replaces it.
- Uses `record_id` when present and explicit `source_id + stored event id` for legacy identity. Error messages
  are replaced by SHA-256 details; persisted health is re-normalized through the existing allowlist and
  bounded to 256 facts per receipt.
- Canonical SHA-256 uses deterministic ordering, source/schema identity, UTC with six microseconds, stable
  finite decimals, and normalized negative zero. The reader imports no estimator persistence or global session.
- No route, startup import, evaluator, concurrency gate, cursor, cache, migration, materialization, or runtime
  activation was added.

## Files changed and purpose

- `app/map/raw_evidence.py`: strict immutable Map reader contracts and canonical digest serialization.
- `app/map/raw_reader.py`: bounded PostgreSQL extraction, transaction enforcement, normalization, and logging.
- `app/map/__init__.py`: exports the additive internal reader contract.
- `tests/test_map_reader.py`: validation, temporal, identity, invalidity, health privacy, digest, fixture replay,
  lookback, unsupported-backend, and estimator-trap regressions.
- `tests/fixtures/map_raw_evidence/golden_v1.json`: stable digest vector.
- `tests/test_docker_e2e.py`: live PostgreSQL mode, transaction, write rejection, timeout, no-write hash,
  exact-cap, overflow, and benchmark evidence.
- `docs/TOMATO_BRAIN_MAP_R1_SPEC.md`, `.ai/CURRENT_STATE.md`: reader implemented but evaluator/API/UI/runtime
  inactive.
- This report and the bounded `agent_run_v1` artifact: implementation and validation evidence.

## Design decisions

- Raw table rows, rather than expanded channel facts, consume the aggregate budget. One selected pod/error row
  can therefore normalize for multiple explicit selectors without falsely multiplying database input.
- Source receipts retain only allowlisted persisted health facts; pod and health error text is hashed before it
  enters the immutable result. Raw payload JSON is absent from the SQL projection.
- The read transaction is explicitly rolled back after materializing rows. Pure normalization and digest work
  occurs outside the snapshot, minimizing database snapshot lifetime while publishing no partial result.
- The 100,000-row engineering limit remains unchanged. Measured memory and serialized size demonstrate that
  future API pagination/concurrency work in #335 remains necessary and is not silently activated here.

## Deviations from brief

- The final benchmark uses exactly 100,000 raw event rows rather than a vaguely "near-cap" count, across the
  requested seven-day/50-source scope. This is stricter boundary evidence and does not change the limit.
- One Docker retry failed before reader execution because the migration container raced PostgreSQL's first
  initialization restart. Cleanup succeeded and a fresh isolated project passed; no application behavior was
  changed for that pre-existing infrastructure race.
- `tools.validate_change` hard-codes `audit_record=None` when an `.ai/agent-runs/` path changes, causing its
  maturity gate to fail on the artifact it requires. Following the documented #332 workaround, the already
  valid audit artifact was held in task-owned state for the successful canonical run, then restored and
  revalidated with `tools.agent_audit` and `git diff --check`.
- Independent reviewer evidence is not claimed by this coding report; it remains a separate required role
  before merge.

## Tests added

- S02/S09 delayed receipt in both modes, stable current/legacy identity, and transport duplicate persistence.
- S04/S05 source omission, mixed pod updates, per-channel lookback, latest error/disable seed, and binding time.
- S14-S16 allowlisted health status/reasons, omission/source receipts, and ingest-time-proxy fidelity.
- Explicit errors, disabled channels, absent metrics, percent bounds/unit checks, non-finite/invalid type paths,
  future clocks, and raw error exclusion.
- Real edge fixture ingestion through validation/persistence followed by reader normalization (`SP-FAIL-011`).
- PostgreSQL transaction-setting verification, rejected write, timeout injection, repeatable digest, and
  unchanged telemetry/state/health/anomaly/simulation count-plus-content hashes.
- Exact 100,000 rows succeed; 100,001 returns `QUERY_LIMIT_EXCEEDED` without a partial batch.
- Golden UTC/numeric/order digest, schema round-trip, Windows-safe handles, and `app*` package discovery.

## Commands run and results

| Status | Command | Result/evidence |
| --- | --- | --- |
| PASS | `python -m pytest -q tests/test_map_reader.py tests/test_map_topology.py tests/test_temporal_integrity.py tests/test_edge_integration_fixtures.py -p no:cacheprovider` | Focused reader/topology/time/ingestion scenarios passed. |
| PASS | `RUN_DOCKER_E2E=1 python -m pytest -q -s tests/test_docker_e2e.py -p no:cacheprovider` | Final isolated PostgreSQL run after sensor-filter and seed-age fixes: 1 passed in 147.08 s; read-only/isolation/timeout/modes/no-write/exact-cap checks passed. |
| FAIL | Same Docker command in a fresh intermediate project | Migration container hit PostgreSQL initialization `connection refused` before reader execution; bounded cleanup completed. |
| PASS | Same Docker command retried with a fresh isolated project | Reader PostgreSQL evidence and benchmark completed; no test retry/weakening was added. |
| PASS | `python -m pytest -q -p no:cacheprovider` | 583 passed, 12 skipped. |
| PASS | `nox -s lint format_check types` | Ruff lint/format and mypy passed. |
| PASS | `git diff --check` | No whitespace errors. |
| PASS | `python -m tools.validate_change --base origin/main --task-key tomato-333-bounded-temporal-raw-evidence-reader --explain --force full` | Canonical final routed validation passed. |
| PASS | `python -m tools.agent_audit .ai/agent-runs/20260909-issue-333-coder.json` | Bounded audit artifact passed. |
| NOT RUN | Production, staging, real bindings/calibration, hardware, external export | Prohibited or outside this isolated synthetic slice. |
| NOT RUN | Evaluator/API/operator UI named consumers | Issues #334-#336 remain inactive and out of scope. |
| PASS | Independent review | Final separate reviewer context returned `APPROVE` with no findings after regressions for non-empty error mappings, duplicate channel identities, and global channel-id uniqueness. |

## Benchmark evidence

Five isolated PostgreSQL reader runs used a synthetic seven-day request with 50 explicit sources and exactly
100,000 `TelemetryEvent` input rows on Windows 11 AMD64 / Python 3.13.6. Measured p50 was 36.967 s, p95
(maximum of five) was 37.003 s, Python peak traced allocation was 524,428,365 bytes, serialized batch size was
47,935,934 bytes, and every run produced digest
`d7e2687c8f8c015a837cc100b5e4aa4d507185fb8a9fcbb66a74441c0190a7e8`. These are development measurements,
not a production SLO; SQL remained bounded by the five-second statement timeout.

## Compatibility checks

- Existing telemetry v1/v2 ingestion and MQTT/HTTP duplicate behavior passed unchanged. No Edge wire, HTTP,
  public, dashboard, estimator, control, or storage-schema contract changed.
- Current and legacy event identities, old edge fixture replay, Map schema serialization, and golden digest
  round-trip passed. Future evaluator #334 is the only named internal consumer of this batch today.
- Package discovery remains explicit as `app*`; `app.map.raw_evidence` and `app.map.raw_reader` import in the
  full suite and runtime build context (`SP-FAIL-015`).

## Safety impact

- No production access/write/deployment, secrets, private infrastructure, external export, or real hardware
  action occurred. Docker evidence used disposable synthetic local data and loopback ports.
- No estimator, Control, Guardrails, Executor, public dataset, or physical path was added or bypassed.
- Rollback is a normal revert or prior immutable application image. There is no migration or data restore;
  PostgreSQL, photos, state/anomaly data, shared services, and Edge spool are preserved.

## Known limitations

- The reader is intentionally not reachable at runtime. Evaluator, API authorization/pagination/concurrency,
  UI, and response-budget enforcement remain owned by #334-#336.
- The cap benchmark demonstrates substantial worst-boundary memory/serialization cost. It does not establish
  production retention, latency, concurrency, or a season-wide SLO.
- Real topology bindings, calibration, private authorization, production data, staging, physical outcomes,
  and external observer evidence remain unverified.

## Documentation changes

- `docs/TOMATO_BRAIN_MAP_R1_SPEC.md` marks topology and reader slices implemented while keeping all runtime
  surfaces inactive.
- `.ai/CURRENT_STATE.md` records the packaged read-only library and absent startup/API integration.

## Manual verification steps

- `PASS`: independent reviewer returned `APPROVE` with no findings after the coder resolved per-channel seed-age, metric/unit, sensor fan-out, non-empty error mapping, and global channel-id uniqueness issues.
- `NOT_RUN`: production/staging, real-data binding/calibration, physical hardware, external export, and
  application-image rollback. Abort on any production path, private data, non-synthetic binding, write,
  estimator call, external export, or hardware access.

## Final diff review

- Scope is limited to the isolated reader contract/adapter, synthetic tests/golden evidence, and truthful
  specification/state/report/audit updates. No migration, index, route, startup hook, or unrelated refactor.
- Raw payloads and error strings are absent from results/logs/golden files; logs contain only mode, bounded
  source/row counts, duration, result code, and digest. No secret, private identifier, debug artifact, weakened
  check, contract drift, or rollback gap was found.
