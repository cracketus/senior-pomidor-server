# Implementation Brief: #334 — Pure target capability and interval evaluation

Status: draft

Planner/version: Codex / Feature Planner 1.1

Approver/date: Unknown — требуется человеческое утверждение brief

Issue/decision: `#334`; по решению пользователя локальный `docs/TOMATO_BRAIN_MAP_R1_SPEC.md` является полной нормой.

Agent run ID / audit artifact: `20260909-issue-334-coder` / `.ai/agent-runs/20260909-issue-334-coder.json`

Execution model: `gpt-5.6-luna`, один Coding Agent без делегирования.

## Problem

После #332 и #333 сервер умеет разрешать версионированную topology и извлекать ограниченный immutable batch сырых свидетельств, но ещё не умеет детерминированно вычислять доступность capability для target или строить временные интервалы результата.

Map описывает доступность наблюдения, а не здоровье растения и не разрешение на полив.

## Desired outcome

Добавить изолированный pure evaluator для `senior-pomidor.map.v1`, который вычисляет capability каждого явно запрошенного target, строит детерминированные UTC half-open интервалы, различает `AS_KNOWN_CORE`/`RECONSTRUCTED`, выдаёт bounded reason codes, assertion type, fidelity и opaque evidence references, не обращаясь к БД, сети, State Estimator, Control, API или оборудованию.

## Current behavior and evidence

- `app/map/models.py` и `provider.py` реализуют строгую immutable topology и binding/profile resolution.
- `origin/main` commit `12ef238` реализует #333: `RawEvidenceRequest`, `RawEvidenceBatch` и read-only PostgreSQL reader.
- `RawEvidenceBatch` сохраняет значения, invalid values, explicit errors, disabled channels, source receipts, timestamps, fidelity и digest.
- `.ai/CURRENT_STATE.md` подтверждает, что evaluator, API и UI ещё не реализованы.
- Локальная `main` чистая, но отстаёт от `origin/main` на commit #333; preflight возвращает `ready_for_task=true`.
- Issue body #334 и внешний scope-документ недоступны (`gh` 401, browser unavailable); по решению пользователя источником истины является локальная спецификация.

## Scope

- Добавить immutable evaluation request/result models и canonical result digest.
- Реализовать pure target/binding evaluation, `ALL_OF`/`ANY_OF` reducers и interval sweep.
- Добавить opaque evidence references без durable DB IDs или raw error text.
- Добавить unit/contract/golden-vector тесты и обновить статус Map в документации.
- Подготовить implementation report и bounded `agent_run_v1`.

## Out of scope

- FastAPI routes, authorization, pagination, concurrency gate и 1 MiB HTTP response enforcement (#335).
- UI, timeline rendering и evidence card (#336).
- Изменения topology YAML, существующих topology digests или reader semantics.
- Миграции, materialization, cache, estimator replay, public export и реальные bindings/calibration.
- Plant-health diagnosis, Control, Guardrails, Executor и физические действия.

## Architecture placement

- Контракты разместить в `app/map/capability.py`, pure алгоритм — в `app/map/evaluator.py`; добавить additive exports из `app/map/__init__.py`.
- Evaluator принимает разрешённую topology, соответствующие `RawEvidenceRequest`/`RawEvidenceBatch` и явные target-capability expressions.
- `TargetCapabilityExpression` содержит target, capability и обязательный `ALL_OF|ANY_OF`; topology v1 не менять.
- Pure evaluator не логирует, не читает время и не выполняет I/O; время, cutoff и версии берутся из immutable artifacts.

## Affected contracts and consumers

- Новый additive internal contract `senior-pomidor.map.v1` capability evaluation.
- Результат содержит evaluation/window/coverage timestamps, mode, cutoff, topology/profile versions, fidelity, ordered target results, half-open intervals, reasons, assertion kind, evidence refs и canonical SHA-256 digest.
- Producer: Map evaluator. Будущие consumers: private API #335 и operator UI #336.
- Edge/MQTT/HTTP ingestion, PostgreSQL schema, State Estimator, Control, dashboards и public export unaffected; существующие contracts/fixtures проходят без изменений.
- Время — UTC microseconds. Soil moisture — explicit `PERCENT` `0..100` с совпадающим profile/calibration; ADC не считается calibrated percent.

## Safety/risk classification

- Task classes: `pure_software`, `schema_data_contract`.
- Risk flags: none.
- `SP-FAIL-009`: проверять версии/digests и owned adapter boundary.
- `SP-FAIL-010`: не смешивать percent/ratio и ADC/percent; boundary tests `0, 1, 50, 100`.
- `SP-FAIL-011`: replay reader/edge fixtures через реальный producer path.
- `SP-FAIL-014`: Windows-safe resources and paths.
- `SP-FAIL-015`: сохранить explicit `app*` package discovery.
- Production, real data, hardware and external export: `NOT_RUN`.

## Proposed implementation sequence

1. Fast-forward чистую `main` до `origin/main` с commit `12ef238`; выполнить preflight и создать `feature/TOMATO-334-map-capability-evaluator` / `tomato-334-map-capability-evaluator`.
2. Добавить strict frozen models: operators/statuses/freshness/assertion/reason/fidelity, expressions, bounded evidence refs, intervals, target results, evaluation batch и canonical digest.
3. Fail closed при несовпадении schema version, mode, window, cutoff, topology revision/digest, profiles или selectors.
4. Построить индекс evidence и выполнить sweep по window/binding boundaries, observation/receipt eligibility и expiry `observation_at + max_age + 1 microsecond`.
5. Зафиксировать leaf semantics: valid fresh → `AVAILABLE/FRESH`; expired → `UNAVAILABLE/STALE`; отсутствующая история → `UNKNOWN/UNKNOWN_HISTORY`; invalid/error → `UNAVAILABLE`; clock-invalid/contradiction → `UNKNOWN`; disabled → `NOT_APPLICABLE`; missing binding → `UNAVAILABLE/MISSING_BINDING`; profile/unit/range/calibration mismatch → `UNKNOWN/MISSING_CALIBRATION`; omission не отменяет value до expiry.
6. Зафиксировать reducers: `ALL_OF` precedence `UNAVAILABLE > UNKNOWN > DEGRADED > AVAILABLE`; `ANY_OF` precedence `AVAILABLE > DEGRADED > UNKNOWN > UNAVAILABLE`; all-N/A → N/A; contradiction всегда → UNKNOWN.
7. Contradiction — несовместимые latest facts одного channel на одном eligibility boundary; несвязанные redundant branches не считать contradiction.
8. Слить соседние идентичные интервалы, сохранить deterministic target/time order, bounded opaque evidence IDs и golden digest.
9. Добавить тесты, exports, spec/current-state updates, implementation report и audit artifact; runtime wiring не добавлять.

## Failure modes

- Version/digest/profile mismatch: typed error без частичного результата.
- Invalid scope: strict validation failure.
- Stale/absent history: successful bounded result, no fabricated outage.
- Invalid/latest error: старое green value не подставляется.
- Late receipt: receipt time только в `AS_KNOWN_CORE`; reconstructed uses observation time.
- Conflicting latest facts: `UNKNOWN/CONTRADICTORY_EVIDENCE`.
- Missing mapping/calibration: non-green typed result; no heuristic conversion.
- Large input: one index and sweep, no quadratic target×evidence scan.
- Any I/O, mutation or estimator invocation: reject and test with traps.

## Backward compatibility

- Изменение additive; topology и raw-evidence models/fixtures не менять.
- Не переписывать `config/topology/*` и digests.
- Existing telemetry v1/v2 and reader golden fixture replay unchanged.
- API отсутствует, mixed-version exposure отсутствует.
- Future breaking changes require a new schema version.

## Testing plan

Required commands:

- `python -m pytest -q tests/test_map_evaluator.py tests/test_map_reader.py tests/test_map_topology.py tests/test_temporal_integrity.py tests/test_edge_integration_fixtures.py -p no:cacheprovider`
- `python -m pytest -q -p no:cacheprovider`
- `nox -s lint format_check types`
- `git diff --check`
- `python -m tools.validate_change --base origin/main --task-key tomato-334-map-capability-evaluator --explain --force full`
- `python -m tools.agent_audit .ai/agent-runs/20260909-issue-334-coder.json`

Required scenarios: S01, S04–S05, S10–S12; two targets; omission/disabled/missing binding/calibration; invalid numeric values; contradiction; both modes; delayed receipt; latest invalidation; exact 1200-second threshold and adjacent microseconds; `ALL_OF`/`ANY_OF`; deterministic ordering/merging; canonical round-trip/golden digest; percent boundaries and ADC rejection; real edge fixture → ingestion → reader → evaluator; no writes to telemetry/state/health/anomaly/simulation; Windows-compatible package/import checks.

Manual checks: independent reviewer required before merge. Production, staging, real data/calibration, hardware and operator UI are `NOT_RUN`.

## Observability

Pure-result observability consists of versions, coverage, fidelity, reasons, evidence refs and digest. `FACT` means stored source evidence, `INFERENCE` means computed availability, and `UNKNOWN` means not proven. Runtime logging/metrics belong to #335. Raw diagnostics, private payloads, DB identities, paths and secrets are excluded.

## Documentation updates

- `docs/TOMATO_BRAIN_MAP_R1_SPEC.md`: evaluator implemented; API/UI/runtime remain `NOT_IMPLEMENTED`.
- `.ai/CURRENT_STATE.md`: pure evaluator packaged but inactive.
- `docs/implementation-reports/ISSUE-334.md`: implementation evidence.
- `.ai/agent-runs/20260909-issue-334-coder.json`: bounded sanitized audit artifact.

## Rollout and rollback

Оставить реализацию неактивной библиотекой; Compose/deployment/canary не требуются. Abort при API/startup wiring, DB write, estimator call, real binding/calibration, private fixture, external export или hardware access. Rollback — revert additive commit или предыдущий immutable application image. Миграции и data restore не нужны.

## Acceptance criteria

- [ ] Два synthetic targets дают независимые deterministic capability intervals.
- [ ] Freshness inclusive на `1200s`, переход ровно на следующей микросекунде.
- [ ] Late arrival различается в двух режимах.
- [ ] Omission не стирает значение до expiry.
- [ ] Invalid/error/disabled latest evidence не заменяется старым green value.
- [ ] Missing binding/calibration, clock invalidity, contradiction и unknown history имеют отдельные reason codes и fail-safe statuses.
- [ ] `ALL_OF`/`ANY_OF` соответствуют truth tables.
- [ ] Evidence refs bounded/opaque и не раскрывают raw diagnostics или DB IDs.
- [ ] Canonical result round-trip и golden digest стабильны.
- [ ] Existing topology, reader, telemetry, estimator, API и public contracts проходят без semantic changes.
- [ ] Все matrix checks записаны как `PASS`, `FAIL` или `NOT_RUN`.
- [ ] Документация/report/audit отражают только реально реализованный evaluator; API/UI остаются будущими.

## Blocking open questions

None. Отсутствующие детали issue body заменены дизайном из локальной спецификации по решению пользователя.

## Evidence and references

- `.ai/CORE_INVARIANTS.md`, `.ai/context-manifest.yaml`, `.ai/test-matrix.yaml`.
- Full selected records `SP-FAIL-009..011`, `SP-FAIL-014..015`.
- `.ai/agents/feature-planner.md`, `.ai/agents/coding-agent.md`, `docs/AGENT_TASK_WORKFLOW.md`.
- `docs/TOMATO_BRAIN_MAP_R1_SPEC.md`.
- `docs/implementation-reports/ISSUE-332.md` and `origin/main:docs/implementation-reports/ISSUE-333.md`.
- `app/map/models.py`, `app/map/provider.py`, `origin/main:app/map/raw_evidence.py`, `origin/main:app/map/raw_reader.py`.
- Unverified: private GitHub issue body #334 and external umbrella scope/ADR pages.

Approval of this brief does not authorize production deployment, production data/secrets access, external export or real hardware activation.
