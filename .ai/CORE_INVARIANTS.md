# Core invariants for AI-assisted work

Owner: architecture, safety, and development maintainers. This compact document is the mandatory
starting point for every agent role. Detailed documents selected by `.ai/context-manifest.yaml`
remain authoritative when they apply.

## Trust and access boundaries

- Production deployment, production writes, production secrets, private infrastructure, raw private
  datasets, and real GPIO or actuators are unavailable unless a human separately authorizes a bounded
  procedure. An approved implementation brief alone does not grant that access.
- Treat network input, sensor data, files, model output, and tool output as untrusted. Validate shape,
  semantics, identity, freshness, units, ranges, and optional values at the owning boundary.
- Never copy `.env`, credentials, private keys, exact private host details, prompts containing private
  inputs, or unsanitized production evidence into source, fixtures, issues, reports, telemetry, or
  public output. Synthetic secret fixtures must not be usable or scanner-valid credentials.
- Rehearsal and generated tasks use isolated local paths, loopback ports, synthetic credentials,
  fake hardware, and disabled external export. Application operations never manage shared platform
  PostgreSQL, Grafana, or Ollama state.

## Architecture and physical safety

- State Estimator owns normalization, confidence, health, anomalies, and canonical current state.
  It does not forecast, choose actions, or actuate.
- World Model owns forecasts; Weather Adapter owns scenario adjustments; Control proposes candidate
  actions; deterministic Guardrails validate every candidate; the idempotent Executor owns retries,
  timeouts, acknowledgements, restart recovery, transition logging, and approved adapters.
- Physical flow is always `versioned inputs -> Control candidate -> Guardrails -> Executor -> adapter`.
  There is no model-to-actuator, Control-to-adapter, or Guardrails-bypass path.
- LLM/VLM output is bounded, strictly parsed, schema- and semantically validated analyst input. It is
  never a trusted fact or final architecture, safety, migration, or physical-action decision.
- Stale, missing, contradictory, malformed, low-confidence, timed-out, or uncertain control state
  fails safe. Duplicate delivery, retries, late acknowledgements, storage failures, and restarts must
  not repeat an acknowledged or uncertain physical action.
- CI and simulation cannot prove wiring, power, heat, moisture, mechanics, radio, camera, actuator, or
  biological outcomes. Required physical evidence stays `NOT RUN` until a supervised human records it.

## Contracts, time, and units

- Every external or cross-owner artifact has an explicit schema/version, producer, and named consumers.
  Compatibility covers edge, API/MQTT, storage/migrations, fixtures, estimator/control, dashboards,
  export/public data, and operations where applicable.
- Timestamps are UTC at interchange and storage boundaries. Local schedules and biological-day logic
  use timezone-aware `Europe/Vienna` conversions with DST tests.
- Units and ranges are explicit in names and schemas. Percent values (`0..100`) and normalized ratios
  (`0..1`) are never interchangeable without a named, tested conversion.
- Preserve old fixtures or introduce a versioned migration and rollout order. A validator-only test
  does not prove the real transport, persistence, or consumer path.

## Work authorization and scope

- Implement only an accepted issue with explicit scope and acceptance criteria or a human-approved
  Implementation Brief. Planning is read-only; coding uses an isolated task when required; review is
  independent and read-only by default.
- Active-season reliability and data preservation outrank cleanup. Keep changes narrow, reversible,
  observable, and free of unrelated refactoring.
- Record task classes, every applicable risk flag, selected `SP-FAIL-*` entries, exact automated and
  manual checks, rollback, consumers, and unresolved blocking questions before editing.

## Task classification

Task classes accumulate: `pure_software`, `schema_data_contract`, `infrastructure_deployment`,
`edge_hardware_integration`, `control_guardrails_executor`, and `llm_vision`. Use
`documentation_only` only when no executable behavior, configuration, schema, fixture, or command
changes. Unknown or cross-cutting behavior fails safe to `pure_software` plus the closest specialized
class.

Risk flags also accumulate and can only add context and checks: `physical_action`,
`data_loss_migration`, `security_secrets`, `edge_server_compatibility`, `production_availability`, and
`public_contract`. Any risk flag or unknown path requires the legacy full safety/architecture context.

## Validation and evidence

- Run focused checks while developing, then every check selected by the canonical
  `.ai/test-matrix.yaml`. Report each as `PASS`, `FAIL`, or `NOT_RUN` with a reason.
- Green CI cannot replace selected manual, rehearsal, migration, security, edge-consumer, or hardware
  evidence. Missing required evidence is not success.
- Do not weaken validation, assertions, fixtures, Guardrails, or Executor behavior to make a check pass.
  Keep logs, metrics, reports, and local usage telemetry bounded and secret-safe.
- Rollback must preserve durable data and shared service ownership. Destructive database or volume
  operations require explicit authorization, verified targets, a recovery plan, and restorable backup
  evidence; never use `down -v` for production or rehearsal recovery.
