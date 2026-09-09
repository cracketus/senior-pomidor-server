# Senior Pomidor Safety Boundaries

Status: current project safety and epistemic boundaries  
Last reviewed: 2026-09-03

Senior Pomidor is an embodied-AI research and engineering project that observes plants and their environment and is progressing toward bounded physical control. This document states what the project does **not** claim or permit and how future AI-assisted control is constrained.

## Biological scope

The current project does **not** involve:

- handling pathogens or pathogen-derived materials;
- wet-lab experimentation;
- DNA/RNA sequencing, design, synthesis, or screening;
- artificial inoculation;
- diagnostic assay development;
- confirmed plant-disease or pathogen diagnosis;
- automatic pesticide or biological-treatment decisions.

Plant-health image analysis is treated as **visual proxy evidence**. Yellowing, wilting, spots, damage, or pest/disease-like patterns may support a hypothesis or a request for human review; they are not confirmed diagnoses.

## AI authority

LLM/VLM output is untrusted advisory input. There is no permitted direct model-to-actuator path.

A model may summarize observations, interpret images, propose hypotheses, suggest measurements, or recommend candidate actions. It may not bypass deterministic control contracts or safety validation.

Any future physical action must:

1. use an explicit typed/versioned action contract;
2. be derived deterministically after probabilistic model output;
3. pass Guardrails using current state, data freshness, confidence, budgets, device state, and hard limits;
4. include expiry/freshness and idempotency semantics so stale or repeated commands do not become uncontrolled actions;
5. be validated again at the edge where local hardware state is known;
6. execute through an approved adapter/Executor;
7. produce an auditable record suitable for effect verification and replay.

If required data are stale, missing, contradictory, low-confidence, timed out, or execution state is uncertain, the system must fail safe rather than invent control-critical values.

## Unattended physical control

Unattended control is roadmap work, not a claim about the current released edge runtime.

Before any unattended actuator path is considered ready, the deployment must have:

- deterministic Guardrails;
- local safety validation and conservative degraded-mode behavior;
- bounded action budgets and explicit command expiry;
- idempotent execution/effect-verification semantics;
- a manual override and documented emergency safe state;
- supervised hardware validation for the actual actuator, wiring, mechanics, and environment;
- logging sufficient to reconstruct state → decision → action → observed outcome.

Software tests or simulation do not prove that real wiring, pumps, fans, shading mechanisms, moisture exposure, heat, radio conditions, or plant response are safe.

## Human review boundary

Human review is required for:

- public plant-health claims that could be read as diagnosis;
- stronger biological causal claims not already supported by validated project evidence;
- experimental protocols that materially change physical treatment of plants;
- promotion of a new probabilistic policy/model toward physical authority;
- publication of images, datasets, or model outputs that have not passed privacy and claims review.

Model-generated labels must remain distinguishable from measured, derived, observed, and human-reviewed evidence.

## Public-data boundary

Senior Pomidor is local-first. Public outputs are deliberate sanitized projections, not raw database or private-photo exports. Secrets, exact private location/infrastructure details, SSIDs, IP addresses, host paths, unreviewed imagery, and raw private logs are excluded from public artifacts.

See [`PUBLIC_DATA_POLICY.md`](PUBLIC_DATA_POLICY.md) for the current publication boundary.

## Related roadmap and implementation work

- [#190 — Predictive Control roadmap](https://github.com/cracketus/senior-pomidor-server/issues/190)
- [#191 — Learning & Experimental Autonomy](https://github.com/cracketus/senior-pomidor-server/issues/191)
- [#195 — shadow-mode policy evaluation / AI authority gate](https://github.com/cracketus/senior-pomidor-server/issues/195)
- [#198 — AI Scientist / experiment-design workflow](https://github.com/cracketus/senior-pomidor-server/issues/198)
- [#201 — production plant vision/VLM phenotyping](https://github.com/cracketus/senior-pomidor-server/issues/201)
- [`senior-pomidor-plant-v2#79`](https://github.com/cracketus/senior-pomidor-plant-v2/issues/79) — edge actuation/safety roadmap context

Internal authoritative engineering rules remain `.ai/CORE_INVARIANTS.md` and `.ai/SAFETY_RULES.md`; this document is their concise reviewer-facing safety boundary, not a replacement for them.
