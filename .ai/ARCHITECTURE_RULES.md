# Architecture invariants

Owner: architecture maintainer. Change only with an approved architecture brief and update all affected contracts/tests. Review at each subsystem introduction. Detailed sources: [`PROJECT.md`](PROJECT.md), [`docs/CONTRACTS.md`](../docs/CONTRACTS.md), [`docs/OPERATIONS.md`](../docs/OPERATIONS.md), and the [State Estimator specification](../docs/state_estimator_spec_v_1_0_en.md).

## Ownership

| Component | Owns | Must not own |
| --- | --- | --- |
| State Estimator | normalization, canonical units, confidence, derived metrics, sensor health/anomalies, current-state assembly | forecasts, target policy, action choice, actuation |
| World Model | forecasts and predictive state from versioned inputs | current-state normalization, actuator commands |
| Weather Adapter | scenario-based target, budget, and sampling adjustments | actuator commands, execution retries |
| Control | candidate action selection from state/forecast/targets | bypassing Guardrails, GPIO, acknowledgements |
| Guardrails | mandatory deterministic validation of every candidate physical action | action execution, model-generated exceptions |
| Executor | execution state machine, idempotency, retries, timeouts, acknowledgements, and transition logging | policy/target selection, guardrail bypass |
| Storage | durable versioned inputs, outputs, transitions, and audit artifacts | hidden control policy |
| LLM/VLM | bounded analysis or communication suggestions | trusted facts, final safety decisions, direct physical actions |

Current implementation status is separate in [`CURRENT_STATE.md`](CURRENT_STATE.md); a documented ownership boundary does not imply that a component exists yet.

## Contract invariants

1. Every external or cross-owner artifact has an explicit schema/version. The producer and every consumer are named in the brief.
2. Units, valid ranges, optional/null semantics, timestamps/timezone, identifiers, and compatibility behavior are explicit. UTC is the interchange boundary; `Europe/Vienna` is used only through timezone-aware conversion.
3. Schema evolution preserves old fixtures or introduces a new version with a migration/rollout plan. Test edge, API, storage, fixtures, dashboards, export/public dataset, and any control consumer separately.
4. Edge/server compatibility is not inferred from server tests. A server-tolerant reader and edge rollout order are required for additive migration.
5. Persist enough version/config/input identity to reproduce consequential derived state or decisions.
6. LLM/VLM responses are parsed, schema-validated, semantically bounded, and handled as unavailable on timeout/malformed output. Extra prose or reasoning never becomes a trusted contract field.

## Runtime invariants

1. No GPIO, bus, camera, or actuator access exists outside approved edge adapters and the Executor path. Simulation/fake backends are the default for generated hardware work.
2. Physical flow is always `versioned state/forecast/targets -> Control candidate -> Guardrails -> Executor -> adapter`. There is no LLM-to-actuator, Control-to-adapter, or Guardrails-bypass shortcut.
3. Duplicate commands, restarts, redelivery, retries, and late acknowledgements are safe. An idempotency key identifies one intended physical action.
4. Retry/timeout policy is bounded and stateful; process restart cannot repeat an already acknowledged or uncertain physical action.
5. Stale, low-confidence, missing, malformed, or contradictory input fails safe. Control-critical values are not silently imputed.
6. Failure paths emit bounded structured logs/health/audit transitions without secrets. Storage failure cannot be hidden behind a successful physical transition.

## Operational invariants

1. Rehearsal has a distinct Compose project, credentials, loopback ports, networks/mounts, and data paths. Grafana Cloud/external export is explicitly disabled.
2. Application lifecycle operations never stop, recreate, or delete platform PostgreSQL, Grafana, or Ollama state.
3. Production changes have a named rollback, pre/post health checks, migration compatibility, and manual acceptance evidence. Agents do not deploy unless separately authorized.
4. During the active season, minimize blast radius; reliability/data-preservation fixes outrank cleanup and unrelated refactoring.
5. Secrets, private keys, exact location, real infrastructure identifiers, and raw private datasets stay out of source, logs, fixtures, briefs, and public outputs.

## Placement examples

| Change | Allowed placement | Forbidden placement |
| --- | --- | --- |
| Convert humidity fraction to `%` and score sensor confidence | State Estimator adapter/validation | Weather Adapter or dashboard query |
| Adjust irrigation budget for a forecast rain scenario | Weather Adapter producing versioned targets/budget | MQTT worker or Executor |
| Choose a candidate watering duration | Control | LLM prompt, GPIO adapter, State Estimator |
| Reject watering because telemetry is stale | Guardrails | Executor retry handler or dashboard |
| Retry a timed-out command without double actuation | Executor state machine | Control loop or Guardrails |
| Summarize a photo | LLM/VLM analyst with strict validated output | Direct command payload or safety override |
| Persist action transitions and acknowledgements | Storage through Executor-owned transition logic | Hardware adapter-only logs |

## Historical change checks

These examples validate that the rules can classify real repository changes:

- `1a9aeeb` / #68, State Estimator layer: **compliant** — normalization/derived state lives under `app/state_estimator/` and does not actuate.
- `6398d9e` / #74, read-only action simulation guardrails: **compliant** — reports `physical_actuation: false`; it would become non-compliant if wired directly to hardware.
- `a480b9f` / #64, active server contracts: **compliant** — contracts, schemas, fixtures, and operational boundaries are explicit.
- `bc16f24` / #114, secure multi-app production layout: **compliant** — application and shared platform service lifecycles are separated.
- `8b3ef35` / #111, Ollama daily story: **compliant** — a bounded optional analyst/communication consumer; no ingestion or actuation authority.
- `532c53b` / #120, migration restore hardening: **compliant** — checksum/readiness/platform boundaries are enforced; destructive shared-service handling would violate the rules.

## Planner/reviewer checklist

- [ ] Each changed responsibility is assigned to exactly one owner above.
- [ ] Implemented/current status is not confused with a future design boundary.
- [ ] All artifacts, units, timezone semantics, versions, producers, and consumers are named.
- [ ] Physical actions pass deterministic Guardrails and idempotent Executor paths using fakes by default.
- [ ] Retries, duplicates, restart, stale input, storage failure, and observability are covered.
- [ ] Rehearsal/production/platform boundaries and rollback are preserved.
- [ ] Relevant `SP-FAIL-*` entries and `TEST_MATRIX.md` checks appear in the Implementation Brief.
