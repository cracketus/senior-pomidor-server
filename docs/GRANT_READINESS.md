# Senior Pomidor Grant Readiness

Status: reviewer-facing project readiness summary  
Last reviewed: 2026-09-03

Senior Pomidor is an open embodied-AI research and engineering programme for learning how to make, validate, execute, and evaluate decisions in a real biological process. Its core value is not a particular sensor or Raspberry Pi: it is the hardware-independent cognitive and safety architecture that turns heterogeneous observations into explicit state, bounded decisions, and eventually verified physical outcomes.

## What exists today

Senior Pomidor already has a working physical observation platform split across two public implementation repositories:

- [`senior-pomidor-plant-v2`](https://github.com/cracketus/senior-pomidor-plant-v2) — Raspberry Pi/Linux edge runtime for real soil, air, light, leaf-temperature, device-health, and camera observations; durable local buffering; HTTP acknowledgement/retry; MQTT mirroring; health/recovery behavior.
- [`senior-pomidor-server`](https://github.com/cracketus/senior-pomidor-server) — FastAPI/PostgreSQL/MQTT Core with idempotent telemetry ingestion, canonical state estimation, sensor-health/anomaly outputs, photo metadata, observability, replay/test infrastructure, and deterministic guardrail/action-simulation foundations.

The system has been operated against real tomato plants and real outdoor environmental conditions. Season 1 produced continuous physical telemetry, images, state-estimation inputs, and real reliability incidents. Those failures are treated as evidence: the project explicitly needs to distinguish infrastructure/sensor failure from biological interpretation.

Current server/edge reliability is not only conceptual. For example, server issue [#200](https://github.com/cracketus/senior-pomidor-server/issues/200) implemented idempotent telemetry ingestion/application acknowledgements needed for at-least-once durable edge delivery.

## What does not exist yet

The current released system must **not** be described as a mature autonomous cultivation platform.

The following remain roadmap/research work unless a later implementation artifact says otherwise:

- a reusable production World Model with validated predictive performance;
- mature predictive control;
- unattended closed-loop physical actuation as a released platform capability;
- production-grade VLM plant phenotyping;
- AI Scientist / experiment-design workflows;
- broad vendor/industrial telemetry adapters;
- spatial/open-field state and control;
- validated generalization across crops or farm environments.

The released edge runtime is primarily an observation/telemetry foundation. Simulation or successful software tests do not prove safe real-world actuator behavior or biological benefit.

## Season 2 / 2027 direction

The programme roadmap targets a complete, explainable loop:

```text
observe
  → estimate state
  → predict/contextualize
  → define targets
  → choose a bounded action
  → validate safety
  → execute
  → observe outcome
  → evaluate
```

The 2027 work is specifically intended to prove that this loop can become hardware/deployment-independent rather than being tied to one balcony, Raspberry Pi, or sensor package. Planned evidence includes replayable Season 1 data, stable observation/capability adapters, World Model/Targets/Control/Guardrails integration, controlled pre-season validation, a renewed reference deployment, and—where a partner is available—a second deployment or telemetry profile.

Relevant roadmap epics:

- [#190 — Predictive Control](https://github.com/cracketus/senior-pomidor-server/issues/190)
- [#191 — Learning & Experimental Autonomy](https://github.com/cracketus/senior-pomidor-server/issues/191)
- [#198 — AI Scientist / experiment-design workflow](https://github.com/cracketus/senior-pomidor-server/issues/198)
- [#201 — production plant vision/VLM phenotyping](https://github.com/cracketus/senior-pomidor-server/issues/201)

## Safety and epistemic boundaries

Senior Pomidor intentionally separates observation, prediction, decision, safety, and execution.

- LLM/VLM output is advisory/untrusted input, not unrestricted actuator authority.
- No direct model-to-actuator path is permitted.
- Future physical actions must pass typed contracts, deterministic Guardrails, freshness/confidence/device checks, edge-local validation, expiry/idempotency semantics, and auditable execution.
- Plant-health visual outputs are proxy evidence or hypotheses, not confirmed disease/pathogen diagnoses.
- The current project does not involve pathogen handling, wet lab, DNA/RNA work, artificial inoculation, or automated pesticide/biological treatment.
- Uncertain or stale control-critical state fails safe.

See [`SAFETY_BOUNDARIES.md`](SAFETY_BOUNDARIES.md) and [`PUBLIC_DATA_POLICY.md`](PUBLIC_DATA_POLICY.md).

## AI/VLM role

LLMs/VLMs may help with image interpretation, scientific evidence synthesis, hypothesis generation, experiment review, explanation, and structured knowledge extraction. They do not define the project’s intelligence by themselves and cannot bypass deterministic safety boundaries.

Current plant-vision work should be described as **visual plant-health proxies**, not diagnosis. Productionization and measurable evaluation remain tracked in [#201](https://github.com/cracketus/senior-pomidor-server/issues/201) and the associated benchmark work.

## Public evidence already available

Public, inspectable artifacts currently include:

- server and edge implementation repositories;
- versioned telemetry and photo schemas;
- Core API/contracts documentation;
- canonical `state_v1`, `sensor_health_v1`, and `anomaly_v1` implementation/tests;
- deterministic Guardrails/action simulation with physical actuation explicitly disabled in simulation;
- reliability, privacy, claims, and public-data policies;
- CI/testing/deployment/replay infrastructure;
- issue-backed architecture and Season 2 implementation plan;
- [`SAFETY_BOUNDARIES.md`](SAFETY_BOUNDARIES.md), the concise reviewer-facing safety boundary.

## Reviewer-facing evidence package

The grant-readiness workstream also includes:

- a small synthetic/sanitized public sample bundle with telemetry, photo metadata, state, and anomaly examples ([#214](https://github.com/cracketus/senior-pomidor-server/issues/214));
- dataset card and no-diagnosis policy ([#215](https://github.com/cracketus/senior-pomidor-server/issues/215));
- a measured VLM benchmark summary and limitations remains pending ([#213](https://github.com/cracketus/senior-pomidor-server/issues/213));
- later state → context → prediction → decision/action → constraint → outcome research artifacts as the closed loop matures.

Public outputs are deliberate sanitized projections. Raw private telemetry, unreviewed photos, exact private location/infrastructure details, secrets, and private logs are not public research artifacts.

## Public-good / open-research intent

Where privacy, security, safety, and licensing permit, Senior Pomidor aims to publish:

- source code and reference implementations;
- versioned contracts/schemas;
- scientific assumptions and provenance;
- evaluation methods and deterministic baselines;
- sanitized or synthetic datasets/fixtures;
- benchmark results and limitations;
- failure cases and negative/null results;
- experiment definitions and action-response methodology.

The project treats transparency as part of the engineering architecture: decisions should become reconstructable from their observations, state, assumptions, constraints, and outcomes.

## Copy-paste project summary

> Senior Pomidor is an open, hardware-independent embodied-AI research programme for making and evaluating decisions in a real biological process. Today it has a working Raspberry Pi edge observation stack and a public Core/server with reliable telemetry ingestion, canonical state estimation, sensor-health/anomaly processing, images, observability, and replay/test infrastructure. The project is progressing toward a safety-governed closed loop of observation → state → prediction/context → targets → bounded decision → Guardrails → execution → observed outcome → evaluation. Autonomous physical control, production VLM phenotyping, and broader farm/field deployments remain roadmap work. LLM/VLM components are advisory and cannot bypass deterministic Guardrails; plant-health visual outputs are treated as proxies/hypotheses, not confirmed diagnoses. The project intends to publish reusable contracts, methods, sanitized data, evaluations, failures, and negative results where safe and legally possible.

## Claim discipline for applications

Grant/application text should explicitly distinguish:

- **CURRENT** — implemented and inspectable now;
- **ARCHITECTURAL** — an adopted project invariant/design boundary, but not proof every integration exists;
- **ROADMAP** — already scoped work, not deployed capability;
- **PROPOSED** — application-specific future work.

Do not convert architectural intent or backlog items into CURRENT claims merely to improve programme fit.
