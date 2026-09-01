# Senior Pomidor Server/Core — Roadmap Through the 2027 Growing Season

**Status:** working roadmap  
**Updated:** 2026-09-01  
**Horizon:** current Server/Core baseline → end of the 2027 growing season  
**Project roadmap:** https://github.com/cracketus/senior-pomidor/blob/main/docs/ROADMAP_2027.md

## Purpose

This document translates the project-level 2027 roadmap into a Server/Core execution roadmap using the existing GitHub backlog.

It is intentionally architectural rather than ticket-by-ticket. The goal is to show how existing epics and major Season 2 release items compose into the Server/Core path from today's observation platform to a reproducible, bounded embodied-AI control system suitable for external pilots and research collaboration.

## Server/Core North Star

By the end of the 2027 growing season, Server/Core should be able to reconstruct and evaluate the complete decision loop:

```text
observation
  -> canonical state
  -> targets/context
  -> prediction
  -> action proposal
  -> guardrail decision
  -> execution/result
  -> observed physical outcome
  -> evaluation / learning
```

The Core must remain independent of a particular sensor vendor, Raspberry Pi revision, farm protocol, or deployment topology. Physical authority remains bounded by typed action contracts, Guardrails, explicit capability/provenance, and deterministic fallback.

## Current Baseline — September 2026

Server/Core already provides the production-oriented observation foundation:

- HTTP/MQTT telemetry ingestion and PostgreSQL persistence;
- canonical State Estimator output, sensor health, anomalies, diagnostics, and private JSONL research logs;
- photo ingestion and metadata storage;
- Grafana observability and public-safe metric projection;
- release/deployment workflows for the dedicated Ubuntu server;
- explicit Edge reliability normalization and visibility completed under [#225](https://github.com/cracketus/senior-pomidor-server/issues/225);
- deterministic replay/simulation foundations and versioned contracts;
- local AI/LLM workflows separated from physical actuator authority.

The main architectural gap is not observation. It is closing the scientifically reconstructable physical loop and proving that the same Core semantics can operate with heterogeneous observation/execution environments.

## Roadmap

| Period | Server/Core stage | Existing backlog epics / major programme items | Architectural focus | Main outcome / evidence |
|---|---|---|---|---|
| **Sep–Oct 2026** | **Consolidate the production observation baseline** | [#247 System verification and cross-repository compatibility](https://github.com/cracketus/senior-pomidor-server/issues/247); completed [#225 Edge reliability observability](https://github.com/cracketus/senior-pomidor-server/issues/225); production-promotion umbrella [#189](https://github.com/cracketus/senior-pomidor-server/issues/189) | Convert current component maturity into system-level evidence: Edge→Core E2E, invariants, compatibility, time semantics, release qualification, backup/recovery/host readiness. Preserve Season 1 data and failures as replay/evaluation material rather than treating them as anecdotal history. | Reproducible current-system baseline; cross-repo compatibility evidence; explicit system invariants; production/recovery evidence suitable as the reference point for Season 2. |
| **Nov 2026–Feb 2027** | **Hardware-independent and pilot-ready Core boundary** | [#261 External telemetry integration framework](https://github.com/cracketus/senior-pomidor-server/issues/261); [#262 Industrial/agricultural protocol gateway](https://github.com/cracketus/senior-pomidor-server/issues/262); Season 2 capability/provenance [#199](https://github.com/cracketus/senior-pomidor-server/issues/199); operator surface [#204](https://github.com/cracketus/senior-pomidor-server/issues/204) | Make native `plant-v2` telemetry one supported source rather than the architectural definition of the system. Introduce canonical external observations, source/logical identity separation, capability and calibration provenance, connector health, and read-only pilot adapters. Stabilize operator/read models for heterogeneous nodes. | A partner sensor system or historical external dataset can enter Tomato Brain without vendor logic leaking into State Estimator/Control. Core can explain source, quality, calibration, capability, freshness, and mapping provenance. |
| **Mar–Apr 2027** | **Pre-season closed-loop foundation** | [#190 Predictive Control programme](https://github.com/cracketus/senior-pomidor-server/issues/190), especially [#192 action/executor contract](https://github.com/cracketus/senior-pomidor-server/issues/192), [#193 Targets Engine](https://github.com/cracketus/senior-pomidor-server/issues/193), [#196 deterministic L2 control](https://github.com/cracketus/senior-pomidor-server/issues/196), [#197 P0 action-response contract](https://github.com/cracketus/senior-pomidor-server/issues/197), plus #247 verification gates | Build and validate the first complete deterministic closed loop before predictive authority. Every physical-action path must be transport-neutral, idempotent, guardrail-gated, provenance-aware, replayable, and able to represent rejected/failed/ambiguous outcomes. | Simulation/HIL/pre-season evidence for `state -> target -> proposal -> guardrail -> execution -> outcome`; deterministic controller available as permanent fallback; first sanitized reconstructed action-response episode. |
| **May–Jun 2027** | **Season 2 deployment and heterogeneous environment support** | #190 deterministic baseline in physical operation; [#261](https://github.com/cracketus/senior-pomidor-server/issues/261) / [#262](https://github.com/cracketus/senior-pomidor-server/issues/262) for pilot integrations; open-field server extensions [#239](https://github.com/cracketus/senior-pomidor-server/issues/239), [#240](https://github.com/cracketus/senior-pomidor-server/issues/240), [#241](https://github.com/cracketus/senior-pomidor-server/issues/241), [#242](https://github.com/cracketus/senior-pomidor-server/issues/242); plant vision [#201](https://github.com/cracketus/senior-pomidor-server/issues/201) as bounded evidence | Operate the reference balcony deployment through the new action-response contracts and bring at least one additional data/deployment profile into the same Core semantics. For field-oriented pilots, extend identity/state/world-model/control spatially rather than forking a separate product. Vision remains evidence with uncertainty, not direct control authority. | Comparable canonical data from heterogeneous sources; one operational deterministic closed-loop deployment; pilot integration path demonstrably reuses the same Core contracts and evaluation pipeline. |
| **Jul–Aug 2027** | **Predictive shadow mode → bounded predictive authority** | #190 predictive path: [#194 World Model v1](https://github.com/cracketus/senior-pomidor-server/issues/194), [#195 shadow-mode policy evaluation and authority gate](https://github.com/cracketus/senior-pomidor-server/issues/195); climate/control extensions such as [#244 drought context](https://github.com/cracketus/senior-pomidor-server/issues/244), [#258 climate stress budget](https://github.com/cracketus/senior-pomidor-server/issues/258), [#269 radiation-aware water/shading model](https://github.com/cracketus/senior-pomidor-server/issues/269) where data/hardware justify them | Compare deterministic and predictive proposals against measured outcomes. Track model error, uncertainty, guardrail rejection, stress exposure, water/resource use, and actuator churn. Grant physical predictive authority only through an explicit reversible envelope while deterministic control remains healthy. | Published shadow-vs-baseline evaluation; bounded World Model error characterization; limited predictive authority for selected actuators/conditions only if predefined gates pass. |
| **Sep–Oct 2027** | **Learning, experiments and cross-environment evaluation** | [#191 Learning & Experimental Autonomy](https://github.com/cracketus/senior-pomidor-server/issues/191); #197 P1 experiment framework; [#198 AI Scientist / experiment-design workflow](https://github.com/cracketus/senior-pomidor-server/issues/198); [#201 vision/VLM](https://github.com/cracketus/senior-pomidor-server/issues/201) as evidence; dataset protection [#97](https://github.com/cracketus/senior-pomidor-server/issues/97) | Use real Season 2 action-response evidence to evaluate learned/adaptive models and controlled experiments. Compare deployment profiles and policies without collapsing uncertainty or negative results. AI Scientist remains research-facing and human-approved; learned control remains shadow-only unless its own authority gate is satisfied. | End-of-season model/policy comparison; reproducible experiment records; public/sanitized action-response dataset and benchmark subset; explicit evidence of what generalized across environments and what did not. |

## Critical Path to the First Scientifically Useful Closed Loop

The existing #190 backlog already defines the core dependency chain. At roadmap level it should be treated as:

```text
#247 / #248 / #249
system verification + invariants
        ↓
#192 + #193
Action contract + Targets Engine
        ↓
#199
capability / hardware provenance
        ↓
#197 P0
action-response episode contract
        ↓
#196
deterministic L2 closed loop
        ↓
#194
World Model v1
        ↓
#195
shadow comparison + authority gate
        ↓
limited predictive authority
        ↓
#191
learning / controlled experiments
```

This path is more important than introducing additional AI components. A sophisticated model without reconstructable action/outcome evidence is not sufficient evidence of embodied intelligence.

## Parallel Enabling Tracks

These epics are strategically useful but should not block the first deterministic closed loop unless a concrete dependency emerges.

| Epic | Role in the 2027 roadmap | Boundary |
|---|---|---|
| [#201 Plant vision / VLM phenotyping](https://github.com/cracketus/senior-pomidor-server/issues/201) | Adds visual plant evidence, uncertainty, phenotyping and experiment inputs. | Evidence only; no direct target/actuator authority. |
| [#204 Operator interfaces](https://github.com/cracketus/senior-pomidor-server/issues/204) | Makes state, forecasts, decisions, guardrail results and failures inspectable to operators and pilot partners. | Read-only first; does not replace Grafana or Guardrails. |
| [#290 Local-first autonomous workflow runtime](https://github.com/cracketus/senior-pomidor-server/issues/290) | Automates research/publication/incident workflows around project evidence. | Separate automation plane; explicitly no physical-control authority. |
| [#253 DSPy evaluation harness](https://github.com/cracketus/senior-pomidor-server/issues/253) | Measures and optimizes selected LLM/VLM research components. | Does not change deterministic Control/Guardrails/Executor. |
| [#275 Codex harness observability](https://github.com/cracketus/senior-pomidor-server/issues/275) | Improves the engineering harness used to build the server. | Development-process quality, not Tomato Brain runtime architecture. |

## Architectural Evolution

| September 2026 Server/Core | End-of-season 2027 target |
|---|---|
| Reliable native Edge telemetry ingestion | Native + external/pilot observation sources behind canonical contracts |
| Canonical state + anomalies | State + explicit targets + prediction + bounded action + observed outcome |
| Sensor/device implementation known mainly through current Edge contract | Capability-based semantics with hardware/calibration/provenance history |
| Monitoring and operator observability | Explainable decision/control read models and operator views |
| Advisory/simulated actions | Deterministic physical L2 baseline with guardrail-gated execution |
| Planned World Model | Evaluated World Model with uncertainty and prediction-error history |
| No predictive physical authority | Shadow-evaluated and explicitly bounded predictive authority where gates pass |
| Telemetry-focused research record | Reconstructable state → action → outcome dataset |
| One dominant deployment topology | Same Core semantics demonstrated across at least two source/deployment profiles |
| AI analysis as side workflows | Evidence-grounded vision/research workflows integrated without bypassing safety |

## End-of-2027 Server/Core Success Criteria

Server/Core should be able to demonstrate that:

1. current and external observation sources enter through stable canonical contracts rather than vendor-specific State Estimator code;
2. logical plant/zone identity is independent of physical node and sensor replacement, with provenance preserved;
3. every physical action used for evaluation is reconstructable from state through observed outcome;
4. deterministic closed-loop control operates without LLM/ML dependencies and remains the safe fallback;
5. World Model predictions are evaluated by horizon with explicit uncertainty and error;
6. predictive authority is earned through stored shadow evidence and a machine-checkable bounded authority gate;
7. one additional deployment/source profile can use the same Core architecture without a parallel bespoke brain;
8. learned models and AI Scientist workflows consume evidence without converting hypotheses into canonical facts or bypassing Guardrails;
9. public/sanitized datasets preserve enough state/action/outcome/provenance semantics for independent replay and research review.

## Collaboration-Relevant Server Interfaces

For a research/pilot partner, the most important Server/Core collaboration surfaces are expected to be:

- external observation/connector contracts — #261;
- industrial/agricultural gateway boundary — #262;
- capability and hardware/calibration provenance — #199;
- cross-repository/system verification — #247;
- Targets/World Model/Control evaluation — #190;
- action-response and experiment contracts — #197/#191;
- vision observations as optional evidence — #201;
- operator/read-model interfaces — #204.

The preferred pilot model is therefore **integration into shared contracts and evaluation**, not a separate one-off server implementation for each farm or research site.
