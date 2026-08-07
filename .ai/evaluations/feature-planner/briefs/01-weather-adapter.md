# Implementation Brief: Weather Adapter integration

Status: draft

Planner/version: Feature Planner 1.1
Issue/decision: Historical fixture FP-01

## Problem

Forecast-aware adjustments are requested, but no provider, forecast schema, target contract or operational fallback is selected.

## Desired outcome

A Weather Adapter deterministically produces versioned target, resource-budget and sampling adjustments from validated scenario inputs, while never selecting or issuing actuator commands.

## Current behavior and evidence

`docs/state_estimator_spec_v_1_0_en.md` places World Model/Weather Adapter downstream of canonical state; `.ai/CURRENT_STATE.md` says weather-adapted targets and forecasts are not implemented. Provider availability and forecast quality are Unknown.

## Scope

- Define input/output contracts, deterministic adjustment policy, no-forecast fallback, simulation fixtures and audit signals.

## Out of scope

- Weather-provider selection/credentials, Control/Executor implementation, real actions, unrelated State Estimator refactoring.

## Architecture placement

The Weather Adapter owns scenario-based targets, budgets and sampling changes. State Estimator remains current-state owner; a future World Model owns forecasts; Control alone selects candidate actions.

## Affected contracts and consumers

New versions for forecast/scenario input and targets/budget/sampling output are required. Units, ranges, Europe/Vienna/UTC semantics and optional forecasts are Unknown pending design. Control and observability are affected future consumers; edge, storage, Grafana/export/public impact must be marked after contract selection.

## Safety/risk classification

Classes: `pure_software`, `schema_data_contract`, `control_guardrails_executor`. Flags: `public_contract` if exposed; `physical_action` only when later consumed by live Control. Apply `SP-FAIL-009`, `SP-FAIL-010`, `SP-FAIL-011`.

## Proposed implementation sequence

1. Approve provider-independent versioned schemas and unit/time semantics.
2. Add deterministic policy and safe unchanged-target fallback.
3. Add scenario fixtures/tests and audit output before any Control integration.
4. Integrate in shadow mode; compare adjustments without actions.

## Failure modes

Missing/stale/malformed forecast, timezone/DST edge, out-of-range adjustment and storage failure must produce bounded observable fallback, never a command.

## Backward compatibility

No existing state contract is reinterpreted. New artifacts are additive; consumers ignore them until explicitly upgraded.

## Testing plan

Run baseline quality/tests plus schema round-trip and deterministic scenarios for no forecast, stale forecast, extreme weather, DST boundary, budget clamps and repeated input. Manual review owns agronomic policy/budget limits.

## Observability

Persist/log input/output versions, scenario time/freshness, bounded adjustment reasons and fallback status without provider secrets.

## Documentation updates

Update contracts, architecture/current state, configuration examples and test matrix paths after implementation.

## Rollout and rollback

Shadow-only first; abort on invalid schema, unstable output or unexplained budget changes. Roll back by disabling the adapter consumer and retaining baseline targets.

## Acceptance criteria

- [ ] Versioned schemas and every consumer are approved; deterministic fixtures cover failure/fallback paths.
- [ ] Shadow output cannot reach actuators and preserves baseline targets when forecast is unusable.

## Blocking open questions

- Which forecast source/schema, adjustment limits, biological horizon, target owner and persistence/publication policy are approved?

## Evidence and references

- `.ai/PROJECT.md`; `.ai/CURRENT_STATE.md`; `docs/state_estimator_spec_v_1_0_en.md`.
- Provider, schemas and policy limits are explicitly unverified.
