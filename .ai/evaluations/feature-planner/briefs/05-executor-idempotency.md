# Implementation Brief: Idempotent physical-action Executor

Status: draft

Planner/version: Feature Planner 1.1
Issue/decision: Historical fixture FP-05

## Problem

A future Executor must prevent duplicate physical actions across retry and restart, while actuator protocol and acknowledgement semantics are unknown.

## Desired outcome

Approved Guardrails outputs enter a durable idempotent Executor state machine that can simulate duplicate, retry, timeout, restart and uncertain acknowledgement without repeated action.

## Current behavior and evidence

`.ai/ARCHITECTURE_RULES.md` defines future ownership; `app/state_estimator/decisions.py` exposes read-only simulation. No production Executor or selected actuator protocol is evidenced.

## Scope

- Define command identity/state transitions, persistence/audit, fake adapter, simulation, manual override/shadow behavior and failure recovery.

## Out of scope

- Actuator selection/wiring, Control policy, bypassing Guardrails, real hardware activation, LLM-derived commands.

## Architecture placement

Control selects candidate; deterministic Guardrails validate; Executor alone owns execution state, idempotency, retry, timeout, acknowledgement and transition logging; fake/approved adapter performs I/O.

## Affected contracts and consumers

New versioned candidate/guardrail result/command/ack/transition artifacts are required. IDs, timing, units, budgets and optional error/ack fields are Unknown. Storage, Control, Guardrails, edge adapter and observability are affected.

## Safety/risk classification

Classes: `control_guardrails_executor`, `schema_data_contract`, `edge_hardware_integration`. Flags: `physical_action`, `production_availability`. Apply architecture duplicate/restart invariants and `SP-FAIL-010/011` where units/fixtures cross boundaries.

## Proposed implementation sequence

1. Approve actuator protocol, acknowledgement and uncertain-state policy.
2. Specify durable state machine/idempotency key and Guardrails-only input.
3. Build fake adapter and deterministic simulation/replay with persistence first.
4. Add shadow/manual override path; physical rollout remains separately approved.

## Failure modes

Duplicate delivery, timeout before/after action, retry, late/conflicting ACK, crash between I/O and persistence, restart, stale/low-confidence input, budget exhaustion, Guardrails block and storage failure all fail safe and remain observable.

## Backward compatibility

Additive future contracts only; no current read-only simulation is reinterpreted. Mixed versions reject unsupported commands before I/O.

## Testing plan

Baseline plus deterministic allowed/blocked Guardrails simulation, duplicate/retry/timeout/late-ACK/restart/storage-failure/manual-override tests with fake adapter. Real hardware is manual and blocked until protocol approval.

## Observability

Durable transition log includes command/idempotency identity, previous/new state, attempt, bounded reason and timestamps; no secrets/model reasoning.

## Documentation updates

Add versioned contracts, state diagram, runbook, manual override and recovery procedures; update current state only after deployment.

## Rollout and rollback

Offline simulation, deterministic replay, shadow mode with I/O disabled, supervised canary. Abort on ambiguous ACK/state or audit failure; disable executor and preserve transition store for reconciliation.

## Acceptance criteria

- [ ] Simulation proves one intended action across duplicates, retries and restarts and blocks stale/low-confidence/Guardrails-rejected input.
- [ ] Every uncertain transition has a safe recovery/manual reconciliation path and no automatic repeat.

## Blocking open questions

- Actuator/protocol, idempotency scope, acknowledgement guarantees, persistence transaction boundary, budgets and manual override authority?

## Evidence and references

- `.ai/ARCHITECTURE_RULES.md`; `app/state_estimator/decisions.py`.
- Hardware/protocol/production Executor facts are Unknown.
